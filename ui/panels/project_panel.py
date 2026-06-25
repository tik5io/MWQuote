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


class ProjectPanel(wx.Panel):
    """Panel for managing project-level information and drawings."""
    PREVIEW_WIDTH = 320
    PREVIEW_HEIGHT = 180

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.on_quantities_changed = None
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
            time_str = f" {entry['time']}" if 'time' in entry else ""
            self.history_list.Append(
                f"{has_xlsx}{entry['devis_ref']} [V{v_idx}] - {entry['date']}{time_str}"
            )

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
