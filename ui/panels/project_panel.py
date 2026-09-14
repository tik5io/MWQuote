# ui/panels/project_panel.py
import wx
import wx.adv
import base64
import io
import os
import time
import tempfile
from domain.document import Document

from ui.dialogs.quantity_manager_dialog import QuantityManagerDialog
from ui.components.document_list_panel import DocumentListPanel
from infrastructure.project_folder_service import ProjectFolderService


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


class ProjectPanel(wx.Panel):
    """Panel for managing project-level information and drawings."""
    PREVIEW_WIDTH = 320
    PREVIEW_HEIGHT = 180

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.on_quantities_changed = None
        self.on_export_fabrication = None
        self.folder_service = ProjectFolderService()
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Grid for Info
        grid = wx.FlexGridSizer(cols=4, hgap=10, vgap=10)
        grid.AddGrowableCol(1, 1)
        grid.AddGrowableCol(3, 1)
        
        grid.Add(wx.StaticText(self, label="Référence:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.ref_ctrl = wx.TextCtrl(self)
        self.ref_ctrl.Bind(wx.EVT_TEXT, lambda e: self.save_project())
        grid.Add(self.ref_ctrl, 1, wx.EXPAND)
        
        grid.Add(wx.StaticText(self, label="Client:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.client_ctrl = wx.TextCtrl(self)
        self.client_ctrl.Bind(wx.EVT_TEXT, lambda e: self.save_project())
        grid.Add(self.client_ctrl, 1, wx.EXPAND)
        
        grid.Add(wx.StaticText(self, label="Date du projet:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.date_ctrl = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY | wx.adv.DP_ALLOWNONE)
        self.date_ctrl.Bind(wx.adv.EVT_DATE_CHANGED, lambda e: self.save_project())
        grid.Add(self.date_ctrl, 1, wx.EXPAND)

        self.prototype_chk = wx.CheckBox(self, label="Prototype")
        self.prototype_chk.Bind(wx.EVT_CHECKBOX, lambda e: self.save_project())
        grid.Add(self.prototype_chk, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(wx.StaticText(self, label=""), 0)  # spacer

        main_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        # Project folder section (dossier réseau du projet série)
        folder_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Dossier projet (réseau)")

        folder_row = wx.BoxSizer(wx.HORIZONTAL)
        self.folder_ctrl = wx.TextCtrl(self)
        self.folder_ctrl.SetHint("Facultatif — ex. Z:\\0 - PROJET SERIE\\CLIENT\\PROJET")
        self.folder_ctrl.Bind(wx.EVT_TEXT, self._on_folder_text)
        folder_row.Add(self.folder_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.folder_status = wx.StaticText(self, label="")
        folder_row.Add(self.folder_status, 0, wx.ALIGN_CENTER_VERTICAL)
        folder_box.Add(folder_row, 0, wx.EXPAND | wx.ALL, 4)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.folder_suggest_btn = wx.Button(self, label="Proposer", size=(-1, -1))
        self.folder_suggest_btn.SetToolTip("Proposer <racine>\\Client\\Référence")
        self.folder_suggest_btn.Bind(wx.EVT_BUTTON, self._on_folder_suggest)
        btn_row.Add(self.folder_suggest_btn, 0, wx.RIGHT, 4)

        self.folder_browse_btn = wx.Button(self, label="Parcourir…")
        self.folder_browse_btn.Bind(wx.EVT_BUTTON, self._on_folder_browse)
        btn_row.Add(self.folder_browse_btn, 0, wx.RIGHT, 4)

        self.folder_open_btn = wx.Button(self, label="Ouvrir")
        self.folder_open_btn.SetToolTip("Ouvrir le dossier dans l'explorateur")
        self.folder_open_btn.Bind(wx.EVT_BUTTON, self._on_folder_open)
        btn_row.Add(self.folder_open_btn, 0, wx.RIGHT, 4)

        self.folder_create_btn = wx.Button(self, label="Créer l'arborescence")
        self.folder_create_btn.SetToolTip("Créer le dossier en copiant l'arborescence du dossier modèle")
        self.folder_create_btn.Bind(wx.EVT_BUTTON, self._on_folder_create)
        btn_row.Add(self.folder_create_btn, 0)

        folder_box.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        # Export Fabrication/Qualité → <dossier projet>\PROCESS
        export_row = wx.BoxSizer(wx.HORIZONTAL)
        self.export_fab_btn = wx.Button(self, label="Exporter Fabrication/Qualité (→ PROCESS)")
        self.export_fab_btn.SetToolTip(
            "Générer le XLSX Fabrication/Qualité (gamme, temps, commentaires) "
            "dans le sous-dossier PROCESS du dossier projet"
        )
        self.export_fab_btn.Bind(wx.EVT_BUTTON, self._on_export_fab)
        export_row.Add(self.export_fab_btn, 0)
        folder_box.Add(export_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

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

        # Quantities Section
        qty_sizer = wx.BoxSizer(wx.HORIZONTAL)
        qty_sizer.Add(wx.StaticText(self, label="Quantités de vente:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        
        self.qty_list_ctrl = wx.StaticText(self, label="")
        qty_sizer.Add(self.qty_list_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        
        self.edit_qty_btn = wx.Button(self, label="Gérer les quantités...")
        self.edit_qty_btn.Bind(wx.EVT_BUTTON, self._on_manage_quantities)
        qty_sizer.Add(self.edit_qty_btn, 0, wx.LEFT, 5)
        
        main_sizer.Add(qty_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Export History Section
        history_sizer = wx.StaticBoxSizer(wx.VERTICAL, self, "Historique des Exports XLSX (double-clic pour ouvrir)")
        self.history_list = wx.ListBox(self, size=(-1, 80))
        self.history_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_history_double_click)
        history_sizer.Add(self.history_list, 1, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(history_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(main_sizer)

    def load_project(self, project):
        self._is_loading = True
        try:
            self.project = project
            self.ref_ctrl.ChangeValue(project.reference or "")
            self.client_ctrl.ChangeValue(project.client or "")
            self.folder_ctrl.ChangeValue(getattr(project, 'project_folder', "") or "")
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
            
            self.prototype_chk.SetValue(bool(getattr(project, 'is_prototype', False)))
            self.doc_list.load_documents(project.documents)
            self._set_preview_bitmap(getattr(project, 'preview_image', None))
            self._update_qty_ui()
            self._update_history_ui()
        finally:
            self._is_loading = False

    def save_project(self):
        """Update the project object with UI values."""
        if getattr(self, "_is_loading", False):
            return
            
        if self.project:
            self.project.reference = self.ref_ctrl.GetValue()
            self.project.client = self.client_ctrl.GetValue()
            self.project.project_folder = self.folder_ctrl.GetValue().strip()
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
    # Dossier projet (réseau)                                              #
    # ------------------------------------------------------------------ #

    def _on_folder_text(self, event):
        self._update_folder_status()
        self.save_project()

    def _update_folder_status(self):
        folder = self.folder_ctrl.GetValue().strip()
        if not folder:
            self.folder_status.SetLabel("(facultatif)")
            self.folder_status.SetForegroundColour(wx.Colour(120, 120, 120))
        elif os.path.isdir(folder):
            self.folder_status.SetLabel("✓ dossier existant")
            self.folder_status.SetForegroundColour(wx.Colour(0, 128, 0))
        else:
            self.folder_status.SetLabel("✗ dossier introuvable")
            self.folder_status.SetForegroundColour(wx.Colour(180, 0, 0))
        self.folder_status.GetParent().Layout()

    def _on_folder_suggest(self, event):
        if not self.project:
            return
        suggestion = self.folder_service.suggest_folder(
            self.client_ctrl.GetValue(), self.ref_ctrl.GetValue()
        )
        if not suggestion:
            wx.MessageBox(
                "Renseignez d'abord le client et/ou la référence pour proposer un chemin.",
                "Dossier projet", wx.OK | wx.ICON_INFORMATION
            )
            return
        self.folder_ctrl.ChangeValue(suggestion)
        self._update_folder_status()
        self.save_project()

    def _on_folder_browse(self, event):
        current = self.folder_ctrl.GetValue().strip()
        default_dir = current if os.path.isdir(current) else self.folder_service.get_root()
        with wx.DirDialog(
            self, "Choisir le dossier projet", defaultPath=default_dir if os.path.isdir(default_dir) else "",
            style=wx.DD_DEFAULT_STYLE
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.folder_ctrl.ChangeValue(dlg.GetPath())
                self._update_folder_status()
                self.save_project()

    def _on_folder_open(self, event):
        folder = self.folder_ctrl.GetValue().strip()
        if not folder:
            return
        if not os.path.isdir(folder):
            wx.MessageBox(
                f"Le dossier n'existe pas encore :\n{folder}\n\n"
                "Utilisez « Créer l'arborescence » pour le générer.",
                "Dossier introuvable", wx.OK | wx.ICON_INFORMATION
            )
            return
        try:
            os.startfile(folder)
        except Exception as e:
            wx.MessageBox(f"Impossible d'ouvrir le dossier :\n{e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_folder_create(self, event):
        if not self.project:
            return
        folder = self.folder_ctrl.GetValue().strip()
        if not folder:
            # Proposer un chemin si le champ est vide
            folder = self.folder_service.suggest_folder(
                self.client_ctrl.GetValue(), self.ref_ctrl.GetValue()
            )
            if not folder:
                wx.MessageBox(
                    "Aucun chemin défini. Renseignez le dossier ou le client/référence.",
                    "Dossier projet", wx.OK | wx.ICON_INFORMATION
                )
                return
            self.folder_ctrl.ChangeValue(folder)
            self.save_project()

        if create_project_folder_interactive(self, self.project, folder, self.folder_service):
            self._update_folder_status()

    def _on_export_fab(self, event):
        if not self.project:
            return
        if self.on_export_fabrication:
            self.on_export_fabrication()

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


    def _update_qty_ui(self):
        if not self.project: return
        qtys = sorted(self.project.sale_quantities)
        self.qty_list_ctrl.SetLabel(", ".join(map(str, qtys)) if qtys else "Aucune")

    def _on_manage_quantities(self, event):
        if not self.project: return
        dlg = QuantityManagerDialog(self, self.project.sale_quantities)
        if dlg.ShowModal() == wx.ID_OK:
            self.project.sale_quantities = dlg.get_quantities()
            self._update_qty_ui()
            if self.on_quantities_changed:
                self.on_quantities_changed(self.project.sale_quantities)
        dlg.Destroy()

    def _get_project_name(self):
        if self.project:
            return self.project.reference or ""
        return ""

    def _update_history_ui(self):
        self.history_list.Clear()
        if not self.project:
            return
        history = getattr(self.project, 'export_history', [])
        for entry in reversed(history):
            has_xlsx = "💾 " if entry.get('xlsx_data_b64') else "   "
            v_idx = entry.get('version_index', 1)
            v_label = self._resolve_version_label(v_idx)
            serie_tag = "[SERIE]" if entry.get('is_serie') else ""
            time_str = f" {entry['time']}" if 'time' in entry else ""
            self.history_list.Append(
                f"{has_xlsx}{entry['devis_ref']} [{v_label}]{serie_tag} - {entry['date']}{time_str}"
            )

    def _resolve_version_label(self, version_index):
        """Retourne le libellé de la version (ou V{n} si non nommée)."""
        for v in getattr(self.project, 'versions', []):
            if v.version_index == version_index:
                return v.label.strip() if v.label and v.label.strip() else f"V{version_index}"
        return f"V{version_index}"

    def _on_history_double_click(self, event):
        if not self.project:
            return
        sel = self.history_list.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        history = list(reversed(getattr(self.project, 'export_history', [])))
        if sel >= len(history):
            return
        entry = history[sel]
        xlsx_b64 = entry.get('xlsx_data_b64')
        if not xlsx_b64:
            wx.MessageBox(
                "Aucun fichier XLSX stocké pour cet export.\n"
                "Les exports futurs seront automatiquement sauvegardés.",
                "Fichier non disponible",
                wx.OK | wx.ICON_INFORMATION
            )
            return
        try:
            xlsx_bytes = base64.b64decode(xlsx_b64)
            filename = entry.get('xlsx_filename', f"{entry.get('devis_ref', 'export')}.xlsx")
            tmp_path = os.path.join(tempfile.gettempdir(), filename)
            with open(tmp_path, 'wb') as f:
                f.write(xlsx_bytes)
            os.startfile(tmp_path)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'ouverture du XLSX:\n{e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def get_quantities(self):
        return sorted(self.quantities)
