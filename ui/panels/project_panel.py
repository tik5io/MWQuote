# ui/panels/project_panel.py
import wx
import wx.adv
import base64
import io
import time
from infrastructure.configuration import ConfigurationService
from domain.document import Document

from ui.dialogs.quantity_manager_dialog import QuantityManagerDialog
from ui.components.document_list_panel import DocumentListPanel


class ProjectPanel(wx.Panel):
    """Panel for managing project-level information and drawings."""
    PREVIEW_WIDTH = 320
    PREVIEW_HEIGHT = 180

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.on_quantities_changed = None
        self.config_service = ConfigurationService()
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
        
        main_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        
        # Drawing Section (Refactored for Multiple PDFs)
        self.doc_list = DocumentListPanel(self, label="Plans de la pièce (PDF) :")
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

        # Milestones Section - Collapsible
        self.milestones_pane = wx.CollapsiblePane(self, label="Suivi de l'Offre (Jalons)")
        self.milestones_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_milestones_pane_toggled)
        milestones_parent = self.milestones_pane.GetPane()
        
        ms_sizer = wx.BoxSizer(wx.VERTICAL)
        
        status_box = wx.BoxSizer(wx.HORIZONTAL)
        status_box.Add(wx.StaticText(milestones_parent, label="Statut actuel :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        
        self.status_choice = wx.Choice(milestones_parent, choices=["En construction", "Finalisée", "Transmise"])
        self.status_choice.Bind(wx.EVT_CHOICE, self._on_status_changed)
        status_box.Add(self.status_choice, 1, wx.EXPAND)
        
        ms_sizer.Add(status_box, 0, wx.EXPAND | wx.ALL, 5)
        
        self.milestone_info = wx.StaticText(milestones_parent, label="")
        ms_sizer.Add(self.milestone_info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        milestones_parent.SetSizer(ms_sizer)
        main_sizer.Add(self.milestones_pane, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.milestones_pane.Collapse(False)
        
        # Tags Section
        tag_sizer = wx.BoxSizer(wx.VERTICAL)
        tag_sizer.Add(wx.StaticText(self, label="Étiquettes de Classification du Projet :"), 0, wx.BOTTOM, 5)
        
        self.tags_wrap_sizer = wx.WrapSizer(wx.HORIZONTAL)
        self.tag_checkboxes = []
        for tag in self.config_service.get_project_tags():
            cb = wx.CheckBox(self, label=tag)
            cb.Bind(wx.EVT_CHECKBOX, lambda e: self.save_project())
            self.tag_checkboxes.append(cb)
            self.tags_wrap_sizer.Add(cb, 0, wx.ALL, 5)
            
        tag_sizer.Add(self.tags_wrap_sizer, 0, wx.EXPAND)
        main_sizer.Add(tag_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # Export History Section
        history_sizer = wx.StaticBoxSizer(wx.VERTICAL, self, "Historique des Exports (XLSX)")
        self.history_list = wx.ListBox(self, size=(-1, 100))
        history_sizer.Add(self.history_list, 1, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(history_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        self.SetSizer(main_sizer)

    def load_project(self, project):
        self._is_loading = True
        try:
            self.project = project
            self.ref_ctrl.ChangeValue(project.reference or "")
            self.client_ctrl.ChangeValue(project.client or "")
            
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
            
            self.doc_list.load_documents(project.documents)
            self._set_preview_bitmap(getattr(project, 'preview_image', None))
            self._update_qty_ui()
            self._update_tags_ui()
            
            # Load status and milestones
            status = getattr(project, "status", "En construction")
            idx = self.status_choice.FindString(status)
            if idx != wx.NOT_FOUND:
                self.status_choice.SetSelection(idx)
            self._update_milestone_ui()
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
            
            # Save project date in ISO format
            dt = self.date_ctrl.GetValue()
            if dt.IsValid():
                self.project.project_date = f"{dt.GetYear()}-{dt.GetMonth() + 1:02d}-{dt.GetDay():02d}"
            else:
                self.project.project_date = None
            
            self.project.tags = [cb.GetLabel() for cb in self.tag_checkboxes if cb.GetValue()]
            self.project.documents = self.doc_list.documents
            
            if hasattr(self, "on_project_changed") and self.on_project_changed:
                self.on_project_changed()

    def _on_preview_pane_toggled(self, event):
        self.Layout()
        top = self.GetTopLevelParent()
        if top:
            top.Layout()
        event.Skip()

    def _on_milestones_pane_toggled(self, event):
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


    def _update_tags_ui(self):
        if not self.project: return
        # Uncheck all first
        for cb in self.tag_checkboxes:
            cb.SetValue(False)
            
        # Check based on project tags
        for tag in self.project.tags:
            for cb in self.tag_checkboxes:
                if cb.GetLabel() == tag:
                    cb.SetValue(True)
                    break

    def _update_milestone_ui(self):
        if not self.project: return
        dates = getattr(self.project, "status_dates", {})
        info = []
        if dates.get("En construction"): info.append(f"🏗️ Construction: {dates['En construction']}")
        if dates.get("Finalisée"): info.append(f"🏁 Finalisée: {dates['Finalisée']}")
        if dates.get("Transmise"): info.append(f"📧 Transmise: {dates['Transmise']}")
        self.milestone_info.SetLabel(" | ".join(info) if info else "Aucun jalon enregistré")

    def _on_status_changed(self, event):
        if not self.project: return
        new_status = self.status_choice.GetStringSelection()
        
        import datetime
        now_str = datetime.date.today().isoformat()
        
        if not hasattr(self.project, "status_dates"):
            self.project.status_dates = {}
            
        self.project.status = new_status
        # Set date for the new status if not already set (or always update? Let's update to current date when picked)
        self.project.status_dates[new_status] = now_str
        
        self._update_milestone_ui()
        self.save_project()

    def _update_history_ui(self):
        if not self.project: return
        self.history_list.Clear()
        history = getattr(self.project, "export_history", [])
        # Show latest first
        for entry in reversed(history):
            time_str = f" {entry['time']}" if 'time' in entry else ""
            self.history_list.Append(f"{entry['devis_ref']} - {entry['date']}{time_str}")

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

    def get_quantities(self):
        return sorted(self.quantities)
