import wx
import os
from infrastructure.persistence import PersistenceService
from ui.panels.graph_analysis_panel import GraphAnalysisPanel
from ui.components.offers_comparison_grid import OffersComparisonGrid
import domain.cost as domain_cost
from domain.operation import SUBCONTRACTING_TYPOLOGY

class ProjectDetailsPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self._build_ui()
        
    def _build_ui(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Header
        self.title_lbl = wx.StaticText(self, label="Aucun projet sélectionné")
        font = self.title_lbl.GetFont()
        font.SetPointSize(12)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.title_lbl.SetFont(font)
        vbox.Add(self.title_lbl, 0, wx.ALL, 10)
        
        vbox.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 10)
        
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
            self.analysis_panel.load_project(self.project)
            self.comparison_grid.project = self.project # Pre-bind project
            self._update_display()
        except Exception as e:
            wx.MessageBox(f"Erreur de chargement: {e}", "Erreur", wx.OK | wx.ICON_ERROR)
            
    def _update_display(self):
        if not self.project:
            return
            
        client_str = f" | {self.project.client}" if self.project.client else ""
        self.title_lbl.SetLabel(f"Projet: {self.project.reference}{client_str}")
        
        # Update Tree
        self.tree.DeleteAllItems()
        root = self.tree.AddRoot("Root")
        
        for op in self.project.operations:
            op_item = self.tree.AppendItem(root, f"🔧 {op.typology or 'Op'} | {op.label}")
            for cost in op.costs.values():
                cost_icon = "💰" if cost.cost_type in [domain_cost.CostType.MATERIAL, domain_cost.CostType.SUBCONTRACTING] else "⚙️" if cost.cost_type == domain_cost.CostType.INTERNAL_OPERATION else "📈"
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
        self.Layout()

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
