# ui/panels/project_panel.py
import wx
import wx.adv
import base64
import io
import os
import time
import tempfile
from domain.document import Document

from ui.components.document_list_panel import DocumentListPanel
from ui.components import trades
from infrastructure.project_folder_service import ProjectFolderService
from infrastructure.configuration import ConfigurationService
from domain.client import SECTORS, SECTOR_OTHER, PROTOTYPE_LABEL, normalize_sector


class ClientManagerDialog(wx.Dialog):
    """Édition de la base clients : renommer, changer le secteur, supprimer."""

    def __init__(self, parent):
        super().__init__(parent, title="Gérer les clients", size=(460, 380),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.cfg = ConfigurationService.get_instance()
        self.changes = {}   # ancien nom -> (nouveau nom, secteur) pour les clients modifiés
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.InsertColumn(0, "Nom", width=250)
        self.list_ctrl.InsertColumn(1, "Secteur", width=150)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._on_edit(e))
        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        btns = wx.BoxSizer(wx.HORIZONTAL)
        edit_btn = wx.Button(self, label="Modifier…")
        edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        del_btn = wx.Button(self, label="Supprimer")
        del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        btns.Add(edit_btn, 0, wx.RIGHT, 6)
        btns.Add(del_btn, 0)
        sizer.Add(btns, 0, wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.CreateStdDialogButtonSizer(wx.CLOSE), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(sizer)
        self.SetAffirmativeId(wx.ID_CLOSE)
        self._fill()

    def _fill(self):
        self.list_ctrl.DeleteAllItems()
        for c in self.cfg.get_clients():
            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), c["name"])
            self.list_ctrl.SetItem(idx, 1, normalize_sector(c.get("sector")))

    def _selected(self):
        idx = self.list_ctrl.GetFirstSelected()
        if idx < 0:
            return None
        return self.list_ctrl.GetItemText(idx, 0), self.list_ctrl.GetItemText(idx, 1)

    def _on_edit(self, event):
        sel = self._selected()
        if not sel:
            return
        old_name, sector = sel
        dlg = NewClientDialog(self, name=old_name, sector=sector, title="Modifier le client")
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            new_name, new_sector = dlg.get_client()
        finally:
            dlg.Destroy()
        if not new_name:
            return
        self.cfg.update_client(old_name, new_name, new_sector)
        # Chaîne les modifications successives d'un même client
        origin = next((o for o, (n, _) in self.changes.items() if n == old_name), old_name)
        self.changes[origin] = (new_name, new_sector)
        self._fill()

    def _on_delete(self, event):
        sel = self._selected()
        if not sel:
            return
        if wx.MessageBox(f"Supprimer le client « {sel[0]} » de la liste ?\n"
                         "Les projets existants conservent leur client.",
                         "Supprimer", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.cfg.remove_client(sel[0])
            self._fill()


class NewClientDialog(wx.Dialog):
    """Saisie d'un client : nom (à saisir, ou à choisir parmi les clients existants) + secteur."""

    def __init__(self, parent, name="", sector=SECTOR_OTHER, title="Nouveau client", intro=""):
        super().__init__(parent, title=title)
        self._clients = ConfigurationService.get_instance().get_clients()
        sizer = wx.BoxSizer(wx.VERTICAL)
        if intro:
            sizer.Add(wx.StaticText(self, label=intro), 0, wx.ALL, 12)
        grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self, label="Nom :"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.name_ctrl = wx.ComboBox(self, value=name, choices=[c["name"] for c in self._clients],
                                     size=(260, -1))
        self.name_ctrl.Bind(wx.EVT_COMBOBOX, self._on_pick_existing)
        grid.Add(self.name_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Secteur d'activité :"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.sector_ctrl = wx.Choice(self, choices=SECTORS)
        self.sector_ctrl.SetSelection(SECTORS.index(normalize_sector(sector)))
        grid.Add(self.sector_ctrl, 1, wx.EXPAND)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        sizer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizerAndFit(sizer)

    def _on_pick_existing(self, event):
        picked = self.name_ctrl.GetStringSelection()
        for c in self._clients:
            if c["name"] == picked:
                self.sector_ctrl.SetSelection(SECTORS.index(normalize_sector(c.get("sector"))))
                break

    def get_client(self):
        return self.name_ctrl.GetValue().strip(), SECTORS[self.sector_ctrl.GetSelection()]


class OverwriteSelectionDialog(wx.Dialog):
    """Liste les fichiers déjà présents qui seraient écrasés et laisse
    l'utilisateur sélectionner ceux à écraser (documente la validation)."""

    def __init__(self, parent, folder, conflicts):
        super().__init__(
            parent, title="Dossier existant — fichiers à écraser",
            size=(600, 460),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(self, label=(
            f"Le dossier existe déjà :\n{folder}\n\n"
            f"{len(conflicts)} fichier(s) portant le même nom sont déjà présents.\n"
            "Cochez ceux à écraser ; décochez ceux à conserver."
        ))
        sizer.Add(intro, 0, wx.ALL, 10)

        self.check_list = wx.CheckListBox(self, choices=conflicts)
        for i in range(len(conflicts)):
            self.check_list.Check(i, True)
        sizer.Add(self.check_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        toggle_row = wx.BoxSizer(wx.HORIZONTAL)
        all_btn = wx.Button(self, label="Tout cocher")
        none_btn = wx.Button(self, label="Tout décocher")
        all_btn.Bind(wx.EVT_BUTTON, lambda e: self._set_all(True))
        none_btn.Bind(wx.EVT_BUTTON, lambda e: self._set_all(False))
        toggle_row.Add(all_btn, 0, wx.RIGHT, 6)
        toggle_row.Add(none_btn, 0)
        sizer.Add(toggle_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        ok_btn = self.FindWindowById(wx.ID_OK)
        if ok_btn:
            ok_btn.SetLabel("Continuer")
        sizer.Add(btns, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(sizer)

    def _set_all(self, state):
        for i in range(self.check_list.GetCount()):
            self.check_list.Check(i, state)

    def get_selected(self):
        return {
            self.check_list.GetString(i)
            for i in range(self.check_list.GetCount())
            if self.check_list.IsChecked(i)
        }


def create_project_folder_interactive(parent, project, folder, service=None):
    """Crée l'arborescence du dossier projet en copiant le dossier modèle.

    Effectue d'abord un pré-scan des fichiers déjà présents qui seraient
    écrasés, puis affiche la liste pour que l'utilisateur valide/sélectionne
    ceux à écraser. Pré-copie ensuite les plans du projet dans
    TECHNIQUE\\PLAN CLIENT\\CHIFFRAGE.

    Retourne True si l'opération s'est déroulée (même partiellement).
    """
    service = service or ProjectFolderService()

    if not service.template_available():
        res = wx.MessageBox(
            f"Le dossier modèle est introuvable :\n{service.get_template_folder()}\n\n"
            "Créer uniquement l'arborescence standard (plans + commercial) ?",
            "Modèle introuvable", wx.YES_NO | wx.ICON_WARNING
        )
        if res != wx.YES:
            return False

    # Pré-scan : documenter les fichiers qui seraient écrasés puis laisser choisir.
    selected_overwrites = set()
    if os.path.isdir(folder):
        try:
            conflicts = service.scan_overwrite_candidates(project, folder)
        except Exception as e:
            wx.MessageBox(
                f"Impossible d'analyser le dossier existant :\n{e}",
                "Dossier existant", wx.OK | wx.ICON_ERROR
            )
            return False
        if conflicts:
            dlg = OverwriteSelectionDialog(parent, folder, conflicts)
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return False  # annulé par l'utilisateur
                selected_overwrites = dlg.get_selected()
            finally:
                dlg.Destroy()

    decider = lambda rel: rel in selected_overwrites

    try:
        tree_stats = service.create_folder_tree(folder, decider)
        plan_stats = service.copy_project_plans(project, folder, decider)
        devis_stats = service.copy_latest_devis_xlsx(project, folder, decider)
        supplier_stats = service.copy_supplier_quotes(project, folder, decider)
    except Exception as e:
        wx.MessageBox(f"Erreur lors de la création du dossier :\n{e}", "Erreur", wx.OK | wx.ICON_ERROR)
        return False

    # Export Fabrication/Qualité → PROCESS (régénéré à la création, honore la sélection).
    fab_stats = {"copied_files": 0, "skipped_files": 0, "errors": []}
    try:
        fab_path = service.fabrication_export_path(project, folder)
        rel_fab = os.path.relpath(fab_path, folder)
        if os.path.exists(fab_path) and rel_fab not in selected_overwrites:
            fab_stats["skipped_files"] = 1
        else:
            from infrastructure.export_service import ExportService
            os.makedirs(os.path.dirname(fab_path), exist_ok=True)
            ExportService().export_fabrication_quality(project, fab_path)
            fab_stats["copied_files"] = 1
    except Exception as e:
        fab_stats["errors"].append(f"Fabrication/Qualité: {e}")

    # Mémoriser le chemin sur le projet
    project.project_folder = folder

    errors = (
        tree_stats.get("errors", [])
        + plan_stats.get("errors", [])
        + devis_stats.get("errors", [])
        + supplier_stats.get("errors", [])
        + fab_stats.get("errors", [])
    )
    summary = (
        f"Dossier projet prêt :\n{folder}\n\n"
        f"• Dossiers créés : {tree_stats.get('created_dirs', 0)}\n"
        f"• Fichiers modèle copiés : {tree_stats.get('copied_files', 0)} "
        f"(ignorés : {tree_stats.get('skipped_files', 0)})\n"
        f"• Plans copiés : {plan_stats.get('copied_files', 0)} "
        f"(ignorés : {plan_stats.get('skipped_files', 0)})\n"
        f"• Devis XLSX copié : {devis_stats.get('copied_files', 0)} "
        f"(ignorés : {devis_stats.get('skipped_files', 0)})\n"
        f"• Devis fournisseur copiés : {supplier_stats.get('copied_files', 0)} "
        f"(ignorés : {supplier_stats.get('skipped_files', 0)})\n"
        f"• Fabrication/Qualité (PROCESS) : {fab_stats.get('copied_files', 0)} "
        f"(ignoré : {fab_stats.get('skipped_files', 0)})"
    )
    if errors:
        summary += "\n\n⚠ Erreurs :\n" + "\n".join(f"- {e}" for e in errors[:8])
        if len(errors) > 8:
            summary += f"\n… (+{len(errors) - 8} autres)"
        wx.MessageBox(summary, "Dossier projet", wx.OK | wx.ICON_WARNING)
    else:
        wx.MessageBox(summary, "Dossier projet", wx.OK | wx.ICON_INFORMATION)
    return True


class ProjectPanel(wx.ScrolledWindow):
    """Panel for managing project-level information and drawings."""
    PREVIEW_WIDTH = 320
    PREVIEW_HEIGHT = 180

    def __init__(self, parent):
        super().__init__(parent)
        self.SetScrollRate(10, 10)   # barres de défilement seulement si le contenu dépasse
        self.project = None
        self.on_export_fabrication = None
        self.folder_service = ProjectFolderService()
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # En-tête métier : tout ce panneau (client, plans, dossier réseau) est l'amont projet
        main_sizer.Add(trades.stripe(self, trades.PROJET), 0, wx.EXPAND)
        main_sizer.Add(trades.caption(self, trades.PROJET, "Contexte et plans"), 0, wx.LEFT | wx.TOP, 10)

        # Infos projet : libellé + champ, une ligne par info (le panneau gauche est étroit)
        grid = wx.FlexGridSizer(cols=2, hgap=8, vgap=8)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label="Référence:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.ref_ctrl = wx.TextCtrl(self)
        self.ref_ctrl.Bind(wx.EVT_TEXT, lambda e: self.save_project())
        grid.Add(self.ref_ctrl, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Client:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.client_ctrl = wx.ComboBox(self, style=wx.CB_READONLY)
        self.client_ctrl.Bind(wx.EVT_COMBOBOX, self._on_client_selected)
        grid.Add(self.client_ctrl, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label=""), 0)
        client_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.new_client_btn = wx.Button(self, label="Nouveau…")
        self.new_client_btn.SetToolTip("Créer un nouveau client (nom + secteur d'activité)")
        self.new_client_btn.Bind(wx.EVT_BUTTON, self._on_new_client)
        client_btns.Add(self.new_client_btn, 0)
        self.manage_client_btn = wx.Button(self, label="Gérer…")
        self.manage_client_btn.SetToolTip("Modifier ou supprimer les clients de la base")
        self.manage_client_btn.Bind(wx.EVT_BUTTON, self._on_manage_clients)
        client_btns.Add(self.manage_client_btn, 0, wx.LEFT, 6)
        grid.Add(client_btns, 0)

        grid.Add(wx.StaticText(self, label="Secteur:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.sector_label = wx.StaticText(self, label="—")
        grid.Add(self.sector_label, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Date:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.date_ctrl = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY | wx.adv.DP_ALLOWNONE)
        self.date_ctrl.Bind(wx.adv.EVT_DATE_CHANGED, lambda e: self.save_project())
        grid.Add(self.date_ctrl, 0)

        grid.Add(wx.StaticText(self, label=""), 0)
        self.prototype_chk = wx.CheckBox(self, label="Prototype")
        self.prototype_chk.SetToolTip(PROTOTYPE_LABEL)
        self.prototype_chk.Bind(wx.EVT_CHECKBOX, lambda e: self.save_project())
        grid.Add(self.prototype_chk, 0, wx.ALIGN_CENTER_VERTICAL)

        main_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        # Project folder section (dossier réseau du projet série)
        # Un seul bouton : il ouvre la fenêtre d'export sélectif (destination,
        # éléments par version, arborescence du dossier modèle).
        folder_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Dossier projet (réseau)")

        self.export_btn = wx.Button(self, label="Exporter…")
        self.export_btn.SetToolTip(
            "Ouvrir la fenêtre d'export : choisir la destination et les éléments "
            "(plans, offres, devis fournisseur, fabrication/qualité) à copier, "
            "rangés par scénario (sous-dossiers V1, V2…)."
        )
        self.export_btn.Bind(wx.EVT_BUTTON, self._on_open_export_dialog)
        folder_box.Add(self.export_btn, 0, wx.ALL, 6)

        # Chemin réseau potentiellement long : abrégé au milieu plutôt que de déborder
        self.folder_status = wx.StaticText(self, label="", style=wx.ST_ELLIPSIZE_MIDDLE)
        self.folder_status.SetMinSize((10, -1))
        folder_box.Add(self.folder_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        main_sizer.Add(folder_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Drawing Section (Refactored for Multiple PDFs)
        self.doc_list = DocumentListPanel(self, label="Plans de la pièce (PDF) :",
                                          project_name_callback=self._get_project_name)
        self.doc_list.on_changed = self.save_project
        main_sizer.Add(self.doc_list, 0, wx.EXPAND | wx.ALL, 10)

        # Project preview image (clipboard import), collapsible to save vertical space
        self.preview_pane = wx.CollapsiblePane(self, label="Preview du projet")
        self.preview_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_preview_pane_toggled)
        preview_parent = self.preview_pane.GetPane()

        preview_box = wx.StaticBoxSizer(wx.VERTICAL, preview_parent, "Image de Preview (Miniature)")
        self.preview_bitmap = wx.StaticBitmap(preview_parent, bitmap=wx.Bitmap(self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT))
        self.preview_bitmap.SetMinSize((self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT))
        self.preview_bitmap.SetBitmap(self._build_blank_preview_bitmap())
        preview_box.Add(self.preview_bitmap, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        button_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.collect_preview_btn = wx.Button(preview_parent, label="Coller depuis presse-papiers")
        self.collect_preview_btn.Bind(wx.EVT_BUTTON, self._on_collect_preview)
        button_bar.Add(self.collect_preview_btn, 0, wx.ALL, 2)

        self.clear_preview_btn = wx.Button(preview_parent, label="Supprimer la preview")
        self.clear_preview_btn.Bind(wx.EVT_BUTTON, self._on_clear_preview)
        button_bar.Add(self.clear_preview_btn, 0, wx.ALL, 2)

        preview_box.Add(button_bar, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        preview_sizer = wx.BoxSizer(wx.VERTICAL)
        preview_sizer.Add(preview_box, 0, wx.EXPAND | wx.ALL, 5)
        preview_parent.SetSizer(preview_sizer)

        main_sizer.Add(self.preview_pane, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.preview_pane.Collapse(False)

        # (Les quantités de vente se gèrent désormais dans chaque phase.)

        # Export History Section
        # (L'historique des offres vit désormais dans l'arbre d'offres de l'onglet Tarif de Vente.)

        self.SetSizer(main_sizer)

    def load_project(self, project):
        self._is_loading = True
        try:
            self.project = project
            self.ref_ctrl.ChangeValue(project.reference or "")
            self._load_client(project)
            self._update_folder_status()

            # Load project date
            if project.project_date:
                try:
                    # Parse ISO format date (YYYY-MM-DD)
                    year, month, day = map(int, project.project_date.split('-'))
                    dt = wx.DateTime()
                    dt.Set(day, month - 1, year)  # month is 0-indexed in wx.DateTime
                    self.date_ctrl.SetValue(dt)
                except (ValueError, AttributeError):
                    pass  # Invalid date format, leave empty
            
            # Le statut prototype est propre à la version affichée
            self.prototype_chk.SetLabel(f"Prototype (S{project.current_version_index})")
            self.prototype_chk.SetValue(bool(project.is_prototype))
            self.doc_list.load_documents(project.documents)
            self._set_preview_bitmap(getattr(project, 'preview_image', None))
        finally:
            self._is_loading = False

    def save_project(self):
        """Update the project object with UI values."""
        if getattr(self, "_is_loading", False):
            return
            
        if self.project:
            self.project.reference = self.ref_ctrl.GetValue()
            self.project.is_prototype = self.prototype_chk.GetValue()

            # Save project date in ISO format
            dt = self.date_ctrl.GetValue()
            if dt.IsValid():
                self.project.project_date = f"{dt.GetYear()}-{dt.GetMonth() + 1:02d}-{dt.GetDay():02d}"
            else:
                self.project.project_date = None

            self.project.documents = self.doc_list.documents
            
            if hasattr(self, "on_project_changed") and self.on_project_changed:
                self.on_project_changed()

    # ------------------------------------------------------------------ #
    # Clients                                                              #
    # ------------------------------------------------------------------ #

    def _refresh_client_choices(self, selected=""):
        names = [c["name"] for c in ConfigurationService.get_instance().get_clients()]
        self.client_ctrl.Set(names)
        if selected in names:
            self.client_ctrl.SetSelection(names.index(selected))

    def _load_client(self, project):
        """Affiche le client du projet. Un client absent de la liste (ancien fichier) ouvre
        la fenêtre de création, pré-remplie avec le nom existant."""
        cfg = ConfigurationService.get_instance()
        name = (project.client or "").strip()
        known = cfg.get_client_sector(name) if name else None
        if known is not None:
            project.client_sector = known   # la base clients fait foi
        self._refresh_client_choices(name)
        self._update_sector_label(project.client_sector if name else "")
        if name and known is None:
            wx.CallAfter(self._prompt_unknown_client, project, name)

    def _prompt_unknown_client(self, project, name):
        if project is not self.project:
            return  # un autre projet a été ouvert entre-temps
        dlg = NewClientDialog(
            self, name=name, sector=project.client_sector or SECTOR_OTHER,
            title="Client non référencé",
            intro=f"Le client « {name} » n'est pas dans la liste.\n"
                  "Validez pour le créer, ou choisissez un client existant.",
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            new_name, sector = dlg.get_client()
        finally:
            dlg.Destroy()
        if new_name:
            ConfigurationService.get_instance().add_client(new_name, sector)
            self._refresh_client_choices(new_name)
            self._apply_client(new_name, sector)

    def _update_sector_label(self, sector):
        self.sector_label.SetLabel(normalize_sector(sector) if sector else "—")
        self.sector_label.GetParent().Layout()

    def _apply_client(self, name, sector):
        self.project.client = name
        self.project.client_sector = sector
        self._update_sector_label(sector)
        if getattr(self, "on_project_changed", None):
            self.on_project_changed()

    def _on_client_selected(self, event):
        if getattr(self, "_is_loading", False) or not self.project:
            return
        name = self.client_ctrl.GetStringSelection()
        sector = ConfigurationService.get_instance().get_client_sector(name) or SECTOR_OTHER
        self._apply_client(name, sector)

    def _on_manage_clients(self, event):
        dlg = ClientManagerDialog(self)
        try:
            dlg.ShowModal()
            changes = dlg.changes
        finally:
            dlg.Destroy()
        current = (self.project.client or "").strip() if self.project else ""
        if current in changes:
            name, sector = changes[current]
            self._refresh_client_choices(name)
            self._apply_client(name, sector)
        else:
            self._refresh_client_choices(current)
            if current:
                sector = ConfigurationService.get_instance().get_client_sector(current)
                if sector is not None and sector != self.project.client_sector:
                    self._apply_client(current, sector)

    def _on_new_client(self, event):
        if not self.project:
            return
        dlg = NewClientDialog(self)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name, sector = dlg.get_client()
        finally:
            dlg.Destroy()
        if not name:
            return
        ConfigurationService.get_instance().add_client(name, sector)
        self._refresh_client_choices(name)
        self._apply_client(name, sector)

    # ------------------------------------------------------------------ #
    # Dossier projet (réseau)                                              #
    # ------------------------------------------------------------------ #

    def _update_folder_status(self):
        folder = (getattr(self.project, 'project_folder', "") or "").strip() if self.project else ""
        if not folder:
            self.folder_status.SetLabel("Aucun dossier associé")
            self.folder_status.SetForegroundColour(wx.Colour(120, 120, 120))
        elif os.path.isdir(folder):
            self.folder_status.SetLabel(f"✓ {folder}")
            self.folder_status.SetForegroundColour(wx.Colour(0, 128, 0))
        else:
            self.folder_status.SetLabel(f"✗ introuvable : {folder}")
            self.folder_status.SetForegroundColour(wx.Colour(180, 0, 0))
        self.folder_status.GetParent().Layout()

    def _on_open_export_dialog(self, event):
        if not self.project:
            return
        from ui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(self, self.project, self.folder_service)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        # Le dialog a pu définir project.project_folder ; refléter + marquer modifié.
        self._update_folder_status()
        self.save_project()

    def _on_preview_pane_toggled(self, event):
        self.Layout()
        top = self.GetTopLevelParent()
        if top:
            top.Layout()
        event.Skip()

    def _build_blank_preview_bitmap(self):
        blank = wx.Bitmap(self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT)
        dc = wx.MemoryDC(blank)
        dc.SetBackground(wx.Brush(wx.Colour(240, 240, 240)))
        dc.Clear()
        dc.SelectObject(wx.NullBitmap)
        return blank

    def _bitmap_from_preview_data(self, preview_data_b64):
        raw = base64.b64decode(preview_data_b64)
        try:
            stream = wx.MemoryInputStream(raw)
            image = wx.Image(stream, wx.BITMAP_TYPE_ANY)
            if not image.IsOk():
                raise ValueError("wx image invalid")
            return self._bitmap_from_wx_image(image)
        except Exception as wx_exc:
            try:
                from PIL import Image
                with Image.open(io.BytesIO(raw)) as pil_image:
                    return self._bitmap_from_pil_image(pil_image.copy())
            except Exception as pil_exc:
                raise ValueError(f"Impossible de decoder la preview (wx: {wx_exc}, PIL: {pil_exc})")

    def _bitmap_from_wx_image(self, image):
        src_w = max(1, image.GetWidth())
        src_h = max(1, image.GetHeight())
        ratio = min(self.PREVIEW_WIDTH / src_w, self.PREVIEW_HEIGHT / src_h)
        dst_w = max(1, int(src_w * ratio))
        dst_h = max(1, int(src_h * ratio))
        scaled = image.Scale(dst_w, dst_h, wx.IMAGE_QUALITY_HIGH)

        canvas = self._build_blank_preview_bitmap()
        dc = wx.MemoryDC(canvas)
        x = (self.PREVIEW_WIDTH - dst_w) // 2
        y = (self.PREVIEW_HEIGHT - dst_h) // 2
        dc.DrawBitmap(wx.Bitmap(scaled), x, y, True)
        dc.SelectObject(wx.NullBitmap)
        return canvas

    def _bitmap_from_pil_image(self, pil_image):
        if pil_image.mode != "RGBA":
            pil_image = pil_image.convert("RGBA")
        src_w, src_h = pil_image.size
        src_w = max(1, src_w)
        src_h = max(1, src_h)
        ratio = min(self.PREVIEW_WIDTH / src_w, self.PREVIEW_HEIGHT / src_h)
        dst_w = max(1, int(src_w * ratio))
        dst_h = max(1, int(src_h * ratio))
        resized = pil_image.resize((dst_w, dst_h))

        from PIL import Image
        canvas = Image.new("RGBA", (self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT), (240, 240, 240, 255))
        x = (self.PREVIEW_WIDTH - dst_w) // 2
        y = (self.PREVIEW_HEIGHT - dst_h) // 2
        canvas.alpha_composite(resized, (x, y))

        return wx.Bitmap.FromBufferRGBA(self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT, bytes(canvas.tobytes()))

    def _set_preview_bitmap(self, preview_doc):
        """Set a small preview image in the UI."""
        if preview_doc and getattr(preview_doc, 'data', None):
            try:
                self.preview_bitmap.SetBitmap(self._bitmap_from_preview_data(preview_doc.data))
            except Exception as exc:
                self.preview_bitmap.SetBitmap(self._build_blank_preview_bitmap())
                wx.MessageBox(f"Erreur rendu preview: {exc}", "Preview", wx.OK | wx.ICON_WARNING)
        else:
            self.preview_bitmap.SetBitmap(self._build_blank_preview_bitmap())
        self.preview_bitmap.Refresh()

    @staticmethod
    def _pil_image_to_png_bytes(pil_image):
        if pil_image.mode not in ("RGB", "RGBA"):
            pil_image = pil_image.convert("RGBA")
        output = io.BytesIO()
        pil_image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    def _on_collect_preview(self, event):
        """Collect an image from clipboard and store it as PNG."""
        if not self.project:
            return

        try:
            from PIL import ImageGrab
        except ImportError:
            wx.MessageBox(
                "Pillow est requis pour la récupération depuis le presse-papiers.\n"
                "Installez-le avec: pip install Pillow",
                "Dépendance manquante",
                wx.OK | wx.ICON_ERROR
            )
            return

        img = ImageGrab.grabclipboard()
        if img is None:
            wx.MessageBox(
                "Aucune image trouvée dans le presse-papiers.\n"
                "Faites une capture d'écran puis réessayez.",
                "Presse-papiers vide",
                wx.OK | wx.ICON_WARNING
            )
            return
        if isinstance(img, list):
            wx.MessageBox(
                "Le presse-papiers contient des fichiers, pas une image bitmap.",
                "Contenu non supporté",
                wx.OK | wx.ICON_WARNING
            )
            return

        try:
            self.preview_bitmap.SetBitmap(self._bitmap_from_pil_image(img))
            self.preview_bitmap.Refresh()
        except Exception as exc:
            wx.MessageBox(f"Image collée mais affichage impossible: {exc}", "Preview", wx.OK | wx.ICON_WARNING)

        try:
            raw_bytes = self._pil_image_to_png_bytes(img)
        except Exception as exc:
            wx.MessageBox(f"Impossible de convertir l'image: {exc}", "Erreur", wx.OK | wx.ICON_ERROR)
            return

        self.project.preview_image = Document(
            filename=f"preview_{int(time.time())}.png",
            data=base64.b64encode(raw_bytes).decode('utf-8')
        )
        self._set_preview_bitmap(self.project.preview_image)
        self.save_project()

    def _on_clear_preview(self, event):
        if not self.project:
            return
        self.project.preview_image = None
        self._set_preview_bitmap(None)
        self.save_project()


    def _get_project_name(self):
        if self.project:
            return self.project.reference or ""
        return ""

    def get_quantities(self):
        return sorted(self.quantities)
