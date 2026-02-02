import wx
import wx.grid
from domain.calculator import Calculator

class OffersComparisonGrid(wx.Panel):
    """Grid component to compare multiple supplier offers (CostItems) for various quantities."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.operation = None
        self._build_ui()

    def _build_ui(self):
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        
        header = wx.StaticText(self, label="COMPARAISON DES OFFRES")
        header.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        header.SetForegroundColour(wx.Colour(100, 100, 100))
        self.sizer.Add(header, 0, wx.ALL, 10)
        
        self.grid = wx.grid.Grid(self)
        self.grid.CreateGrid(0, 0)
        self.grid.EnableEditing(False)
        self.grid.SetDefaultCellAlignment(wx.ALIGN_RIGHT, wx.ALIGN_CENTER_VERTICAL)
        self.sizer.Add(self.grid, 1, wx.EXPAND | wx.ALL, 5)
        
        self.SetSizer(self.sizer)

    def load_operation(self, operation, project):
        self.operation = operation
        self.project = project
        self._refresh_data()

    def _refresh_data(self):
        if not self.operation or not self.project:
            return

        self.grid.ClearGrid()
        if self.grid.GetNumberRows() > 0:
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        if self.grid.GetNumberCols() > 0:
            self.grid.DeleteCols(0, self.grid.GetNumberCols())

        quantities = sorted(self.project.sale_quantities)
        offers = list(self.operation.costs.values())

        if not offers or not quantities:
            return

        # Setup columns (Offers)
        self.grid.AppendCols(len(offers))
        for i, offer in enumerate(offers):
            label = offer.name
            if offer.is_active:
                label += " (ACTIVE)"
            self.grid.SetColLabelValue(i, label)
            
        # Setup rows (Quantities)
        self.grid.AppendRows(len(quantities))
        for i, qty in enumerate(quantities):
            self.grid.SetRowLabelValue(i, f"Q: {qty}")
            
            # Fill values
            for j, offer in enumerate(offers):
                res = Calculator.calculate_item(offer, qty)
                price = res.unit_sale_price
                self.grid.SetCellValue(i, j, f"{price:.4f} €")
                
                # Visual cue for active offer
                if offer.is_active:
                    self.grid.SetCellBackgroundColour(i, j, wx.Colour(240, 255, 240)) # Very light green
                    self.grid.SetCellTextColour(i, j, wx.Colour(0, 100, 0)) # Dark green
                
        self.grid.AutoSize()
        self.Layout()
