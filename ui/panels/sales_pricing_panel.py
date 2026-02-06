# ui/panels/sales_pricing_panel.py
import wx
import wx.grid as gridlib
from domain.project import Project
from domain.cost import ConversionType, CostItem, CostType, PricingType
from ui.components.cost_item_editor import CostItemEditor
from ui.components.result_summary_panel import ResultSummaryPanel
from infrastructure.logging_service import get_module_logger

logger = get_module_logger("SalesPricing", "sales_pricing.log")

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

        # Header with title and volume margin rate
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(self.grid_panel, label="Récapitulatif des Prix de Vente")
        title.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        header_sizer.Add(title, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)

        header_sizer.AddStretchSpacer()

        header_sizer.AddStretchSpacer()

        grid_sizer.Add(header_sizer, 0, wx.EXPAND)

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
        self.cost_editor.on_changed = self._on_cost_changed
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
        self.grid.Bind(gridlib.EVT_GRID_CELL_CHANGED, self._on_grid_cell_changed)

    def load_project(self, project: Project):
        self.project = project
        self.refresh_data()

    def refresh_data(self):
        if not self.project: return
        logger.debug("refresh_data start")
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
            for cost in op._get_active_costs():
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

        # Add Volume Margin rate row
        margin_row = self.grid.GetNumberRows()
        self.grid.AppendRows(1)
        self.grid.SetCellValue(margin_row, 1, "COEFF. MARGE / VOLUME")
        self.grid.SetReadOnly(margin_row, 1, True)
        self.grid.SetCellBackgroundColour(margin_row, 0, wx.Colour(255, 245, 230))
        self.grid.SetCellBackgroundColour(margin_row, 1, wx.Colour(255, 245, 230))
        self.grid.SetCellFont(margin_row, 1, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.margin_row_idx = margin_row

        for i, q in enumerate(qtys):
            rate = self.project.volume_margin_rates.get(q, 1.0)
            self.grid.SetCellValue(margin_row, 2 + i, f"{rate:.2f}")
            self.grid.SetCellBackgroundColour(margin_row, 2 + i, wx.Colour(255, 250, 240))
            self.grid.SetCellTextColour(margin_row, 2 + i, wx.Colour(200, 100, 0))
            self.grid.SetCellFont(margin_row, 2 + i, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            # This row is editable

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
        logger.debug("refresh_data done")

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
            self._notify_main_frame()

    def _on_cost_changed(self, temp_cost):
        """Callback appelé quand un coût est modifié en temps réel."""
        if not self.current_cost or not self.current_op:
            return
        logger.debug(f"on_cost_changed | op={self.current_op.code} cost={self.current_cost.name}")
        new_name = self.cost_editor.prop_name.GetValue().strip()
        if new_name and new_name != self.current_cost.name:
            if not self.current_op.rename_cost(self.current_cost.name, new_name):
                # Revert invalid rename to avoid desync
                logger.warning(f"rename_cost rejected | old={self.current_cost.name} new={new_name}")
                self.cost_editor.prop_name.ChangeValue(self.current_cost.name)
                return
        if self.cost_editor.apply_changes():
            # Rafraîchir la grille pour refléter les changements
            self.refresh_data()
            self._notify_main_frame()
        else:
            logger.warning("apply_changes returned False")

    def _notify_main_frame(self):
        """Notifie le MainFrame des changements pour rafraîchir les autres panels."""
        parent = self.GetParent()
        while parent and not hasattr(parent, 'on_operation_updated'):
            parent = parent.GetParent()
        if parent and hasattr(parent, 'on_operation_updated') and parent.on_operation_updated:
            parent.on_operation_updated(None)

    def refresh_quantities(self):
        """Rafraîchit les sélecteurs de quantités dans les sous-composants."""
        if self.cost_editor.IsShown():
            self.cost_editor.result_panel._refresh_qty_choice()

    def _on_grid_cell_changed(self, event):
        row = event.GetRow()
        col = event.GetCol()
        if hasattr(self, 'margin_row_idx') and row == self.margin_row_idx and col >= 2:
            try:
                val = float(self.grid.GetCellValue(row, col).replace(',', '.'))
                qtys = sorted(self.project.sale_quantities)
                q = qtys[col - 2]
                self.project.volume_margin_rates[q] = val
                self.refresh_data()
                self._notify_main_frame()
            except ValueError:
                self.refresh_data() # Reset to valid value
        event.Skip()
