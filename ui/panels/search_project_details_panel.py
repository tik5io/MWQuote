import wx
import os
import base64
import io
from infrastructure.persistence import PersistenceService
from ui.panels.graph_analysis_panel import GraphAnalysisPanel
from ui.components.offers_comparison_grid import OffersComparisonGrid
import domain.cost as domain_cost
from domain.operation import SUBCONTRACTING_TYPOLOGY

class ProjectDetailsPanel(wx.Panel):
    PREVIEW_WIDTH = 320
    PREVIEW_HEIGHT = 180

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self._build_ui()
        
    # Colour constants for mode badges
    _BADGE_PROTO = (wx.Colour(210, 110, 20),  wx.WHITE)   # orange, white text
    _BADGE_SERIE = (wx.Colour(40,  140,  60),  wx.WHITE)   # green,  white text

    def _make_badge(self, parent, label, bg, fg):
        """Renders a small coloured pill label."""
        pnl = wx.Panel(parent)
        pnl.SetBackgroundColour(bg)
        lbl = wx.StaticText(pnl, label=f"  {label}  ")
        lbl.SetForegroundColour(fg)
        f = lbl.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        f.SetPointSize(9)
        lbl.SetFont(f)
        sz = wx.BoxSizer(wx.HORIZONTAL)
        sz.Add(lbl, 0, wx.TOP | wx.BOTTOM, 3)
        pnl.SetSizer(sz)
        return pnl

    def _build_ui(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Header
        self.title_lbl = wx.StaticText(self, label="Aucun projet sélectionné")
        font = self.title_lbl.GetFont()
        font.SetPointSize(12)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.title_lbl.SetFont(font)
        vbox.Add(self.title_lbl, 0, wx.ALL, 10)

        # Mode badges row (hidden until a project is loaded)
        self._badge_row = wx.BoxSizer(wx.HORIZONTAL)
        self._badge_proto = self._make_badge(self, "PROTOTYPE", *self._BADGE_PROTO)
        self._badge_serie = self._make_badge(self, "PRODUCTION SÉRIE", *self._BADGE_SERIE)
        self._badge_row.Add(self._badge_proto, 0, wx.LEFT | wx.BOTTOM, 6)
        self._badge_row.Add(self._badge_serie, 0, wx.LEFT | wx.BOTTOM, 6)
        self._badge_proto.Hide()
        self._badge_serie.Hide()
        vbox.Add(self._badge_row, 0, wx.LEFT, 10)

        self.preview_bitmap = wx.StaticBitmap(self, bitmap=wx.Bitmap(self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT))
        self.preview_bitmap.SetMinSize((self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT))
        self.preview_bitmap.SetBitmap(self._build_blank_preview_bitmap())
        vbox.Add(self.preview_bitmap, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        self.open_preview_btn = wx.Button(self, label="Ouvrir Preview")
        self.open_preview_btn.Bind(wx.EVT_BUTTON, self._on_open_preview)
        self.open_preview_btn.Disable()
        vbox.Add(self.open_preview_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        vbox.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 10)

        # Version selector row
        version_row = wx.BoxSizer(wx.HORIZONTAL)
        version_row.Add(wx.StaticText(self, label="Version :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        self.version_choice = wx.Choice(self, choices=[])
        self.version_choice.Bind(wx.EVT_CHOICE, self._on_version_changed)
        version_row.Add(self.version_choice, 1, wx.EXPAND | wx.RIGHT, 6)
        vbox.Add(version_row, 0, wx.EXPAND | wx.BOTTOM, 6)

        # Splitter for Tree vs Graph
        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        self.splitter.SetMinimumPaneSize(100)
        
        # Middle: Tree of operations
        self.tree = wx.TreeCtrl(self.splitter, style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT | wx.TR_LINES_AT_ROOT)
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_tree_selection)
        
        # Bottom area: dynamic switching (Chart or Offer Comparison)
        self.bottom_container = wx.Panel(self.splitter)
        self.bottom_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Bottom: Analysis Chart
        self.analysis_panel = GraphAnalysisPanel(self.bottom_container)
        self.analysis_panel.SetMinSize((-1, 300))
        self.bottom_sizer.Add(self.analysis_panel, 1, wx.EXPAND)
        
        # Bottom: Offer Comparison
        self.comparison_grid = OffersComparisonGrid(self.bottom_container)
        self.comparison_grid.Hide()
        self.bottom_sizer.Add(self.comparison_grid, 1, wx.EXPAND)
        
        self.bottom_container.SetSizer(self.bottom_sizer)
        
        # Split!
        self.splitter.SplitHorizontally(self.tree, self.bottom_container, -400) # Start with 400px for bottom
        self.splitter.SetSashGravity(1.0) # Bottom keeps its size on resize
        
        vbox.Add(self.splitter, 1, wx.EXPAND | wx.ALL, 5)
        
        self.SetSizer(vbox)
        
    def load_project(self, project_path):
        try:
            self.project = PersistenceService.load_project(project_path)
            self._populate_version_selector()
            self.analysis_panel.load_project(self.project)
            self.comparison_grid.project = self.project
            self._update_display()
        except Exception as e:
            wx.MessageBox(f"Erreur de chargement: {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _populate_version_selector(self):
        self.version_choice.Clear()
        if not self.project:
            return
        versions = getattr(self.project, 'versions', [])
        for v in versions:
            label = f"V{v.version_index}"
            if getattr(v, 'label', ''):
                label += f" — {v.label}"
            self.version_choice.Append(label, v.version_index)
        # Select current version
        cur = self.project.current_version_index
        for i in range(self.version_choice.GetCount()):
            if self.version_choice.GetClientData(i) == cur:
                self.version_choice.SetSelection(i)
                break

    def _on_version_changed(self, event):
        if not self.project:
            return
        idx = self.version_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        v_index = self.version_choice.GetClientData(idx)
        self.project.switch_to_version(v_index)
        self.analysis_panel.load_project(self.project)
        self.comparison_grid.project = self.project
        self._update_display()

    def reset_view(self, title: str = "Aucun projet sélectionné"):
        """Reset details panel state when nothing should be displayed."""
        self.project = None
        self.title_lbl.SetLabel(title)
        self._badge_proto.Hide()
        self._badge_serie.Hide()
        self.version_choice.Clear()
        self.tree.DeleteAllItems()
        self.tree.AddRoot("Root")
        self.analysis_panel.Show()
        self.comparison_grid.Hide()
        self.bottom_sizer.Layout()
        self.bottom_container.Layout()
        self.Layout()
            
    def _update_display(self):
        if not self.project:
            return

        client_str = f" | {self.project.client}" if self.project.client else ""
        self.title_lbl.SetLabel(f"Projet: {self.project.reference}{client_str}")

        # Show/hide mode badges
        tags_lower = [t.lower() for t in (getattr(self.project, 'tags', None) or [])]
        self._badge_proto.Show(any("proto" in t for t in tags_lower))
        self._badge_serie.Show(getattr(self.project, 'serie_data', None) is not None)
        self.Layout()
        
        # Update Tree
        self.tree.DeleteAllItems()
        root = self.tree.AddRoot("Root")
        
        for op in self.project.operations:
            op_item = self.tree.AppendItem(root, f"🔧 {op.typology or 'Op'} | {op.label}")
            for cost in op.costs.values():
                cost_icon = "💰" if cost.cost_type in [domain_cost.CostType.MATERIAL, domain_cost.CostType.SUBCONTRACTING] else "⚙️" if cost.cost_type == domain_cost.CostType.INTERNAL_OPERATION else "🛠️" if cost.cost_type == domain_cost.CostType.TOOLING else "📈"
                label = f"{cost_icon} {cost.name}"
                
                is_archived = (op.typology == SUBCONTRACTING_TYPOLOGY and not cost.is_active)
                if is_archived:
                    label = f"📁 [ARCHIVE] {cost.name}"
                
                c_item = self.tree.AppendItem(op_item, label)
                if is_archived:
                    self.tree.SetItemTextColour(c_item, wx.Colour(150, 150, 150))
                
                self.tree.SetItemData(c_item, {"type": "cost", "cost": cost, "operation": op})
            
            self.tree.SetItemData(op_item, {"type": "operation", "operation": op})
        
        self.tree.ExpandAll()
        self._set_preview_bitmap(getattr(self.project, 'preview_image', None))
        self.Layout()

    def _set_preview_bitmap(self, preview_doc):
        if preview_doc and getattr(preview_doc, 'data', None):
            try:
                raw = base64.b64decode(preview_doc.data)
                stream = wx.MemoryInputStream(raw)
                image = wx.Image(stream, wx.BITMAP_TYPE_ANY)
                if not image.IsOk():
                    raise ValueError("wx image invalid")
                self.preview_bitmap.SetBitmap(self._bitmap_from_wx_image(image))
                self.open_preview_btn.Enable()
                return
            except Exception:
                try:
                    from PIL import Image
                    with Image.open(io.BytesIO(raw)) as pil_image:
                        self.preview_bitmap.SetBitmap(self._bitmap_from_pil_image(pil_image.copy()))
                        self.open_preview_btn.Enable()
                        return
                except Exception:
                    pass

        self.preview_bitmap.SetBitmap(self._build_blank_preview_bitmap())
        self.open_preview_btn.Disable()

    def _build_blank_preview_bitmap(self) -> wx.Bitmap:
        blank = wx.Bitmap(self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT)
        dc = wx.MemoryDC(blank)
        dc.SetBackground(wx.Brush(wx.Colour(240, 240, 240)))
        dc.Clear()
        dc.SelectObject(wx.NullBitmap)
        return blank

    def _bitmap_from_wx_image(self, image: wx.Image) -> wx.Bitmap:
        src_w = max(1, image.GetWidth())
        src_h = max(1, image.GetHeight())
        ratio = min(self.PREVIEW_WIDTH / src_w, self.PREVIEW_HEIGHT / src_h)
        dst_w = max(1, int(src_w * ratio))
        dst_h = max(1, int(src_h * ratio))
        scaled = image.Scale(dst_w, dst_h, wx.IMAGE_QUALITY_HIGH)

        canvas = wx.Bitmap(self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT)
        dc = wx.MemoryDC(canvas)
        dc.SetBackground(wx.Brush(wx.Colour(240, 240, 240)))
        dc.Clear()
        x = (self.PREVIEW_WIDTH - dst_w) // 2
        y = (self.PREVIEW_HEIGHT - dst_h) // 2
        dc.DrawBitmap(wx.Bitmap(scaled), x, y, True)
        dc.SelectObject(wx.NullBitmap)
        return canvas

    def _bitmap_from_pil_image(self, pil_image) -> wx.Bitmap:
        from PIL import Image
        if pil_image.mode != "RGBA":
            pil_image = pil_image.convert("RGBA")
        src_w, src_h = pil_image.size
        src_w = max(1, src_w)
        src_h = max(1, src_h)
        ratio = min(self.PREVIEW_WIDTH / src_w, self.PREVIEW_HEIGHT / src_h)
        dst_w = max(1, int(src_w * ratio))
        dst_h = max(1, int(src_h * ratio))
        resized = pil_image.resize((dst_w, dst_h))

        canvas = Image.new("RGBA", (self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT), (240, 240, 240, 255))
        x = (self.PREVIEW_WIDTH - dst_w) // 2
        y = (self.PREVIEW_HEIGHT - dst_h) // 2
        canvas.alpha_composite(resized, (x, y))
        return wx.Bitmap.FromBufferRGBA(self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT, bytes(canvas.tobytes()))

    def _on_open_preview(self, event):
        if not self.project or not getattr(self.project, 'preview_image', None):
            return
        doc = self.project.preview_image
        if not doc.data:
            return

        try:
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(doc.filename)[1] or '.png') as tmp:
                tmp.write(base64.b64decode(doc.data))
                tmp_path = tmp.name
            os.startfile(tmp_path)
        except Exception as e:
            wx.MessageBox(f"Échec ouverture preview : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_tree_selection(self, event):
        item = event.GetItem()
        if not item.IsOk() or not self.project:
            return
            
        data = self.tree.GetItemData(item)
        if not data:
            # Root or null data
            self.analysis_panel.Show()
            self.comparison_grid.Hide()
        elif data["type"] == "operation" and data["operation"].typology == SUBCONTRACTING_TYPOLOGY:
            # Show offer comparison!
            self.analysis_panel.Hide()
            self.comparison_grid.Show()
            self.comparison_grid.load_operation(data["operation"], self.project)
        else:
            # Project or other operation
            self.analysis_panel.Show()
            self.comparison_grid.Hide()
            
        self.bottom_sizer.Layout()
        self.bottom_container.Layout()
        self.Layout()
