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
from ui.components.notes_editor import NotesEditor
from ui.components import trades
from infrastructure.project_folder_service import ProjectFolderService
from infrastructure.configuration import ConfigurationService
from domain.client import SECTORS, normalize_sectors


class ClientManagerDialog(wx.Dialog):
    """Édition de la base clients : renommer, changer le secteur, supprimer."""

    def __init__(self, parent):
        super().__init__(parent, title="Gérer les clients", size=(380, 380),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.cfg = ConfigurationService.get_instance()
        self.changes = {}   # ancien nom -> nouveau nom pour les clients renommés
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.InsertColumn(0, "Nom", width=320)
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
            self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), c["name"])

    def _selected(self):
        idx = self.list_ctrl.GetFirstSelected()
        if idx < 0:
            return None
        return self.list_ctrl.GetItemText(idx, 0)

    def _on_edit(self, event):
        sel = self._selected()
        if not sel:
            return
        old_name = sel
        dlg = NewClientDialog(self, name=old_name, title="Modifier le client")
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            new_name = dlg.get_client()
        finally:
            dlg.Destroy()
        if not new_name:
            return
        self.cfg.update_client(old_name, new_name)
        # Chaîne les renommages successifs d'un même client
        origin = next((o for o, n in self.changes.items() if n == old_name), old_name)
        self.changes[origin] = new_name
        self._fill()

    def _on_delete(self, event):
        sel = self._selected()
        if not sel:
            return
        if wx.MessageBox(f"Supprimer le client « {sel} » de la liste ?\n"
                         "Les projets existants conservent leur client.",
                         "Supprimer", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.cfg.remove_client(sel)
            self._fill()


class NewClientDialog(wx.Dialog):
    """Saisie d'un client : son nom (à saisir, ou à choisir parmi les clients existants).

    Un client n'a que son nom ; les domaines d'application (médical, aéronautique) se cochent
    sur chaque projet.
    """

    def __init__(self, parent, name="", title="Nouveau client", intro=""):
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
        grid.Add(self.name_ctrl, 1, wx.EXPAND)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        sizer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizerAndFit(sizer)

    def get_client(self) -> str:
        return self.name_ctrl.GetValue().strip()


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
        self.SetScrollRate(0, 10)    # défilement vertical seulement : le contenu s'adapte à la largeur
        self.ShowScrollbars(wx.SHOW_SB_NEVER, wx.SHOW_SB_DEFAULT)
        self._preview_source = None   # image d'aperçu (wx.Image d'origine), redimensionnée à la largeur du panneau
        self._preview_width = 0
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.project = None
        self.on_export_fabrication = None
        self.folder_service = ProjectFolderService()
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # En-tête métier : tout ce panneau (client, plans, dossier réseau) est l'amont projet
        main_sizer.Add(trades.stripe(self, trades.PROJET), 0, wx.EXPAND)
        main_sizer.Add(trades.caption(self, trades.PROJET, "Contexte et plans"), 0, wx.LEFT | wx.TOP, 10)

        # Aperçu du projet : l'image seule (sans cadre) et deux petits boutons
        self.preview_bitmap = wx.StaticBitmap(self, bitmap=self._placeholder_bitmap(self.PREVIEW_WIDTH))
        main_sizer.Add(self.preview_bitmap, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        button_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.collect_preview_btn = wx.Button(self, label="Coller", size=(60, 22))
        self.collect_preview_btn.SetToolTip("Coller l'image du presse-papiers (capture d'écran) comme aperçu du projet")
        self.collect_preview_btn.Bind(wx.EVT_BUTTON, self._on_collect_preview)
        button_bar.Add(self.collect_preview_btn, 0)
        self.clear_preview_btn = wx.Button(self, label="Supprimer", size=(75, 22))
        self.clear_preview_btn.SetToolTip("Supprimer l'aperçu du projet")
        self.clear_preview_btn.Bind(wx.EVT_BUTTON, self._on_clear_preview)
        button_bar.Add(self.clear_preview_btn, 0, wx.LEFT, 4)
        main_sizer.Add(button_bar, 0, wx.ALIGN_CENTER | wx.TOP, 4)

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
        self.new_client_btn.SetToolTip("Créer un nouveau client")
        self.new_client_btn.Bind(wx.EVT_BUTTON, self._on_new_client)
        client_btns.Add(self.new_client_btn, 0)
        self.manage_client_btn = wx.Button(self, label="Gérer…")
        self.manage_client_btn.SetToolTip("Modifier ou supprimer les clients de la base")
        self.manage_client_btn.Bind(wx.EVT_BUTTON, self._on_manage_clients)
        client_btns.Add(self.manage_client_btn, 0, wx.LEFT, 6)
        grid.Add(client_btns, 0)

        # Domaines d'application du PROJET (cumulables, ou aucun) : pilotent les mentions de traçabilité
        grid.Add(wx.StaticText(self, label="Domaine:"), 0, wx.ALIGN_CENTER_VERTICAL)
        sector_row = wx.BoxSizer(wx.HORIZONTAL)
        self.sector_chks = {}
        for sector in SECTORS:
            chk = wx.CheckBox(self, label=sector)
            chk.SetToolTip("Domaine(s) d'application de ce projet, cumulables. Détermine les mentions de "
                           "traçabilité des offres : une norme non cochée (ISO 13485 médical, ISO 9100 "
                           "aéronautique) est indiquée « Non applicable ».")
            chk.Bind(wx.EVT_CHECKBOX, lambda e: self.save_project())
            sector_row.Add(chk, 0, wx.RIGHT, 12)
            self.sector_chks[sector] = chk
        grid.Add(sector_row, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Date:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.date_ctrl = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY | wx.adv.DP_ALLOWNONE)
        self.date_ctrl.Bind(wx.adv.EVT_DATE_CHANGED, lambda e: self.save_project())
        grid.Add(self.date_ctrl, 0)

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

        # Bloc-notes du projet : texte mis en forme, enregistré avec le projet
        main_sizer.Add(trades.caption(self, trades.PROJET, "Bloc-notes"), 0, wx.LEFT | wx.TOP, 10)
        self.notes = NotesEditor(self, on_changed=self._on_notes_changed)
        main_sizer.Add(self.notes, 0, wx.EXPAND | wx.ALL, 10)

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
            
            for sector, chk in self.sector_chks.items():
                chk.SetValue(sector in project.sectors)
            self.doc_list.load_documents(project.documents)
            self._set_preview_bitmap(getattr(project, 'preview_image', None))
            self.notes.set_xml(getattr(project, 'notes', "") or "")
        finally:
            self._is_loading = False

    def save_project(self):
        """Update the project object with UI values."""
        if getattr(self, "_is_loading", False):
            return
            
        if self.project:
            self.project.reference = self.ref_ctrl.GetValue()
            self.project.sectors = normalize_sectors(s for s, chk in self.sector_chks.items() if chk.GetValue())

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
        self._refresh_client_choices(name)
        if name and not cfg.has_client(name):
            wx.CallAfter(self._prompt_unknown_client, project, name)

    def _prompt_unknown_client(self, project, name):
        if project is not self.project:
            return  # un autre projet a été ouvert entre-temps
        dlg = NewClientDialog(
            self, name=name, title="Client non référencé",
            intro=f"Le client « {name} » n'est pas dans la liste.\n"
                  "Validez pour le créer, ou choisissez un client existant.",
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            new_name = dlg.get_client()
        finally:
            dlg.Destroy()
        if new_name:
            ConfigurationService.get_instance().add_client(new_name)
            self._refresh_client_choices(new_name)
            self._apply_client(new_name)

    def _apply_client(self, name):
        self.project.client = name
        if getattr(self, "on_project_changed", None):
            self.on_project_changed()

    def _on_client_selected(self, event):
        if getattr(self, "_is_loading", False) or not self.project:
            return
        self._apply_client(self.client_ctrl.GetStringSelection())

    def _on_manage_clients(self, event):
        dlg = ClientManagerDialog(self)
        try:
            dlg.ShowModal()
            changes = dlg.changes
        finally:
            dlg.Destroy()
        current = (self.project.client or "").strip() if self.project else ""
        if current in changes:
            self._refresh_client_choices(changes[current])
            self._apply_client(changes[current])
        else:
            self._refresh_client_choices(current)

    def _on_new_client(self, event):
        if not self.project:
            return
        dlg = NewClientDialog(self)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.get_client()
        finally:
            dlg.Destroy()
        if not name:
            return
        ConfigurationService.get_instance().add_client(name)
        self._refresh_client_choices(name)
        self._apply_client(name)

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

    # ------------------------------------------------------------------ #
    # Aperçu du projet                                                     #
    # ------------------------------------------------------------------ #

    def _placeholder_bitmap(self, width):
        """Zone grise « Aucune image » quand le projet n'a pas d'aperçu."""
        bmp = wx.Bitmap(max(int(width), 80), 64)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(240, 240, 240)))
        dc.Clear()
        dc.SetTextForeground(wx.Colour(150, 150, 150))
        text = "Aucune image"
        tw, th = dc.GetTextExtent(text)
        dc.DrawText(text, (bmp.GetWidth() - tw) // 2, (bmp.GetHeight() - th) // 2)
        dc.SelectObject(wx.NullBitmap)
        return bmp

    @staticmethod
    def _wx_image_from_pil(pil_image):
        rgba = pil_image.convert("RGBA")
        image = wx.Image(rgba.size[0], rgba.size[1])
        image.SetData(rgba.convert("RGB").tobytes())
        image.SetAlpha(rgba.getchannel("A").tobytes())
        return image

    def _image_from_preview_data(self, preview_data_b64):
        raw = base64.b64decode(preview_data_b64)
        try:
            image = wx.Image(io.BytesIO(raw), wx.BITMAP_TYPE_ANY)
            if image.IsOk():
                return image
        except Exception:
            pass        # wx ne sait pas lire ce format : repli sur Pillow
        try:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as pil_image:
                return self._wx_image_from_pil(pil_image.copy())
        except Exception as exc:
            raise ValueError(f"Impossible de décoder l'aperçu ({exc})")

    def _available_preview_width(self):
        return max(min(self.PREVIEW_WIDTH, self.GetClientSize().width - 28), 120)

    def _render_preview(self):
        """Affiche l'aperçu (ou « Aucune image ») à la largeur disponible du panneau."""
        max_w, max_h = self._available_preview_width(), self.PREVIEW_HEIGHT
        src = self._preview_source
        if src is not None and src.IsOk():
            w, h = max(1, src.GetWidth()), max(1, src.GetHeight())
            ratio = min(max_w / w, max_h / h)
            bmp = wx.Bitmap(src.Scale(max(1, int(w * ratio)), max(1, int(h * ratio)), wx.IMAGE_QUALITY_HIGH))
        else:
            bmp = self._placeholder_bitmap(max_w)
        self._preview_width = max_w
        self.preview_bitmap.SetBitmap(bmp)
        self.Layout()
        self.FitInside()

    def _on_size(self, event):
        event.Skip()
        # L'aperçu suit la largeur du panneau (replié / élargi) ; hors de l'événement pour éviter les rebonds
        wx.CallAfter(self._on_resized)

    def _on_resized(self):
        try:
            if self._available_preview_width() != self._preview_width:
                self._render_preview()
        except RuntimeError:
            pass        # panneau détruit entre-temps

    def _set_preview_bitmap(self, preview_doc):
        """Affiche l'aperçu enregistré dans le projet (rien si absent ou illisible)."""
        self._preview_source = None
        if preview_doc and getattr(preview_doc, 'data', None):
            try:
                self._preview_source = self._image_from_preview_data(preview_doc.data)
            except Exception as exc:
                wx.MessageBox(f"Erreur rendu preview: {exc}", "Preview", wx.OK | wx.ICON_WARNING)
        self._render_preview()

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


    def _on_notes_changed(self, xml):
        """Bloc-notes modifié (signalé avec un léger délai) : le projet est à enregistrer."""
        if getattr(self, "_is_loading", False) or not self.project:
            return
        self.project.notes = xml
        if getattr(self, "on_project_changed", None):
            self.on_project_changed()

    def flush(self):
        """Envoie tout de suite le bloc-notes au projet (avant un enregistrement)."""
        self.notes.flush()

    def _get_project_name(self):
        if self.project:
            return self.project.reference or ""
        return ""

    def get_quantities(self):
        return sorted(self.quantities)
