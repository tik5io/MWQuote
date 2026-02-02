# ui/panels/sales_pricing_panel.py
import wx
import wx.grid as gridlib
from domain.project import Project
from domain.cost import ConversionType, CostItem, CostType, PricingType
from ui.components.cost_item_editor import CostItemEditor
from ui.components.result_summary_panel import ResultSummaryPanel

class SalesPricingPanel(wx.Panel):
    """Grid display of pricing results with a sidebar for full item properties."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.current_cost = None
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Splitter for Grid and Detail Panel
        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        
        # Left side: Grid
        self.grid_panel = wx.Panel(self.splitter)
        grid_sizer = wx.BoxSizer(wx.VERTICAL)
        
        title_sizer = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(self.grid_panel, label="Récapitulatif des Prix de Vente")
        title.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title_sizer.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        grid_sizer.Add(title_sizer, 0, wx.EXPAND)
        
        self.grid = gridlib.Grid(self.grid_panel)
        self.grid.CreateGrid(0, 2)
        self.grid.SetColLabelValue(0, "Opération")
        self.grid.SetColLabelValue(1, "Désignation")
        grid_sizer.Add(self.grid, 1, wx.EXPAND | wx.ALL, 5)
        self.grid_panel.SetSizer(grid_sizer)
        
        # Right side: Detail Panel
        self.detail_panel = wx.ScrolledWindow(self.splitter, style=wx.VSCROLL)
        self.detail_panel.SetScrollRate(0, 20)
        self.detail_panel.SetBackgroundColour(wx.Colour(245, 245, 245))
        self.detail_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.detail_title = wx.StaticText(self.detail_panel, label="Paramètres de l'article")
        self.detail_title.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.detail_sizer.Add(self.detail_title, 0, wx.ALL, 10)
        
        # Use shared component
        self.cost_editor = CostItemEditor(self.detail_panel)
        self.cost_editor.on_changed = lambda temp_cost: None
        self.detail_sizer.Add(self.cost_editor, 0, wx.EXPAND)
        self.cost_editor.Hide()
        
        self.placeholder = wx.StaticText(self.detail_panel, label="Sélectionnez un item pour éditer ses paramètres")
        self.detail_sizer.Add(self.placeholder, 0, wx.ALL, 20)
        
        self.save_btn = wx.Button(self.detail_panel, label="Appliquer les changements")
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_apply_details)
        self.detail_sizer.Add(self.save_btn, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        self.save_btn.Hide()
        
        self.detail_panel.SetSizer(self.detail_sizer)
        
        self.splitter.SplitVertically(self.grid_panel, self.detail_panel, 700)
        main_sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

        self.grid.Bind(gridlib.EVT_GRID_SELECT_CELL, self._on_select_cell)

    def load_project(self, project: Project):
        self.project = project
        self.refresh_data()

    def refresh_data(self):
        if not self.project: return
        self.grid.BeginBatch()
        if self.grid.GetNumberRows() > 0:
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
            
        qtys = sorted(self.project.sale_quantities)
        target_cols = 2 + len(qtys)
        curr_cols = self.grid.GetNumberCols()
        if curr_cols < target_cols: self.grid.AppendCols(target_cols - curr_cols)
        elif curr_cols > target_cols: self.grid.DeleteCols(target_cols, curr_cols - target_cols)
        
        for i, q in enumerate(qtys):
            self.grid.SetColLabelValue(2 + i, f"Q{q} (€/p)")
            
        self.row_to_cost = {}
        for op in self.project.operations:
            op_start_row = self.grid.GetNumberRows()
            for cost in op.costs.values():
                row = self.grid.GetNumberRows()
                self.grid.AppendRows(1)
                self.row_to_cost[row] = (cost, op)
                self.grid.SetCellValue(row, 0, op.code)
                self.grid.SetReadOnly(row, 0, True)
                self.grid.SetCellValue(row, 1, cost.name)
                self.grid.SetReadOnly(row, 1, True)
                for i, q in enumerate(qtys):
                    val = cost.calculate_sale_price(q) # Unit price
                    self.grid.SetCellValue(row, 2 + i, f"{val:.2f}")
                    self.grid.SetReadOnly(row, 2 + i, True)
                    self.grid.SetCellBackgroundColour(row, 2 + i, wx.Colour(240, 240, 255))
            
            # Add Operation Subtotal
            subtotal_row = self.grid.GetNumberRows()
            self.grid.AppendRows(1)
            self.grid.SetCellValue(subtotal_row, 1, f"SOUS-TOTAL {op.code}")
            self.grid.SetReadOnly(subtotal_row, 1, True)
            self.grid.SetCellBackgroundColour(subtotal_row, 0, wx.Colour(235, 235, 235))
            self.grid.SetCellBackgroundColour(subtotal_row, 1, wx.Colour(235, 235, 235))
            self.grid.SetCellFont(subtotal_row, 1, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

            for i, q in enumerate(qtys):
                val = op.total_with_margins(q) # Unit price
                self.grid.SetCellValue(subtotal_row, 2 + i, f"{val:.2f}")
                self.grid.SetReadOnly(subtotal_row, 2 + i, True)
                self.grid.SetCellBackgroundColour(subtotal_row, 2 + i, wx.Colour(235, 235, 235))
                self.grid.SetCellFont(subtotal_row, 2 + i, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        total_row = self.grid.GetNumberRows()
        self.grid.AppendRows(1)
        self.grid.SetCellValue(total_row, 1, "PRIX DE VENTE TOTAL (€/pièce)")
        self.grid.SetReadOnly(total_row, 1, True)
        self.grid.SetCellBackgroundColour(total_row, 1, wx.Colour(230, 230, 230))
        for i, q in enumerate(qtys):
            val = self.project.total_price(q) # Unit price
            self.grid.SetCellValue(total_row, 2 + i, f"{val:.2f}")
            self.grid.SetReadOnly(total_row, 2 + i, True)
            self.grid.SetCellTextColour(total_row, 2 + i, wx.BLUE)
            self.grid.SetCellBackgroundColour(total_row, 2 + i, wx.Colour(230, 230, 230))
            self.grid.SetCellFont(total_row, 2 + i, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        self.grid.AutoSizeColumns()
        self.grid.EndBatch()

    def _on_select_cell(self, event):
        row = event.GetRow()
        if row in self.row_to_cost:
            cost, op = self.row_to_cost[row]
            self._show_details(cost, op)
        else:
            self._clear_details()
        event.Skip()

    def _clear_details(self):
        self.cost_editor.Hide()
        self.placeholder.Show()
        self.save_btn.Hide()
        self.detail_panel.Layout()

    def _show_details(self, cost, parent_op):
        self.current_cost = cost
        self.current_op = parent_op
        self.cost_editor.Show()
        self.save_btn.Show()
        self.cost_editor.load_cost(cost, self.project)
        self.placeholder.Hide() # Added hide
        self.detail_panel.Layout()

    def _on_apply_details(self, event):
        if not self.current_cost or not self.current_op: return
        
        # Handle renaming first to keep dict key in sync
        new_name = self.cost_editor.prop_name.GetValue().strip()
        if new_name and new_name != self.current_cost.name:
            self.current_op.rename_cost(self.current_cost.name, new_name)

        if self.cost_editor.apply_changes():
            self.refresh_data()
            # Try to notify app of changes if possible
            parent = self.GetParent()
            while parent and not hasattr(parent, 'on_operation_updated'):
                parent = parent.GetParent()
            if parent and parent.on_operation_updated:
                # Notify with None to avoid project header reload but trigger total refreshes
                parent.on_operation_updated(None)
