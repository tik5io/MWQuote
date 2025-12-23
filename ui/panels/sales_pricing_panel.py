# ui/panels/sales_pricing_panel.py
import wx
import wx.grid as gridlib
from domain.project import Project

class SalesPricingPanel(wx.Panel):
    """Panel for displaying and managing sales pricing across different quantities."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.quantities = [1, 10, 20, 50, 100, 200, 500, 1000]
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Title and Toolbar
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(self, label="Grille des tarifs de vente")
        title.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        header_sizer.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        header_sizer.AddStretchSpacer()
        
        self.add_qty_btn = wx.Button(self, label="+ Quantité")
        self.add_qty_btn.Bind(wx.EVT_BUTTON, self._on_add_quantity)
        header_sizer.Add(self.add_qty_btn, 0, wx.ALL, 5)

        self.refresh_btn = wx.Button(self, label="Actualiser")
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self.refresh_data())
        header_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)

        main_sizer.Add(header_sizer, 0, wx.EXPAND)

        # Grid
        self.grid = gridlib.Grid(self)
        self.grid.CreateGrid(0, 4)
        self.grid.SetColLabelValue(0, "Quantité")
        self.grid.SetColLabelValue(1, "Coût de base total (€)")
        self.grid.SetColLabelValue(2, "Prix de vente total (€)")
        self.grid.SetColLabelValue(3, "Prix unitaire (€/p)")
        
        # Set column widths
        self.grid.SetColSize(0, 100)
        self.grid.SetColSize(1, 150)
        self.grid.SetColSize(2, 150)
        self.grid.SetColSize(3, 150)
        
        main_sizer.Add(self.grid, 1, wx.EXPAND | wx.ALL, 10)

        # Context menu for deleting rows
        self.grid.Bind(gridlib.EVT_GRID_CELL_RIGHT_CLICK, self._on_grid_right_click)

        self.SetSizer(main_sizer)

    def load_project(self, project: Project):
        self.project = project
        self.refresh_data()

    def refresh_data(self):
        """Update the grid with current project data and quantities."""
        if not self.project:
            return

        self.quantities.sort()
        
        # Clear existing rows
        if self.grid.GetNumberRows() > 0:
            self.grid.DeleteRows(0, self.grid.GetNumberRows())

        for qty in self.quantities:
            row = self.grid.GetNumberRows()
            self.grid.AppendRows(1)
            
            # Calculations
            base_cost = sum(op.total_cost(qty) for op in self.project.operations)
            total_price = self.project.total_price(qty)
            unit_price = total_price / qty if qty > 0 else 0
            
            self.grid.SetCellValue(row, 0, str(qty))
            self.grid.SetCellValue(row, 1, f"{base_cost:.2f}")
            self.grid.SetCellValue(row, 2, f"{total_price:.2f}")
            self.grid.SetCellValue(row, 3, f"{unit_price:.4f}")
            
            # Make read-only
            for col in range(4):
                self.grid.SetReadOnly(row, col, True)
            
            # Alignment
            self.grid.SetCellAlignment(row, 0, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            self.grid.SetCellAlignment(row, 1, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            self.grid.SetCellAlignment(row, 2, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            self.grid.SetCellAlignment(row, 3, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)

    def _on_add_quantity(self, event):
        dlg = wx.TextEntryDialog(self, "Entrez une nouvelle quantité :", "Ajouter une quantité")
        if dlg.ShowModal() == wx.ID_OK:
            try:
                qty = int(dlg.GetValue())
                if qty > 0 and qty not in self.quantities:
                    self.quantities.append(qty)
                    self.refresh_data()
                elif qty <= 0:
                    wx.MessageBox("La quantité doit être supérieure à 0.", "Erreur", wx.OK | wx.ICON_ERROR)
            except ValueError:
                wx.MessageBox("Veuillez entrer un nombre entier valide.", "Erreur", wx.OK | wx.ICON_ERROR)
        dlg.Destroy()

    def _on_grid_right_click(self, event):
        row = event.GetRow()
        if row < 0: return
        
        menu = wx.Menu()
        del_item = menu.Append(wx.ID_ANY, f"Supprimer la quantité {self.quantities[row]}")
        self.Bind(wx.EVT_MENU, lambda e: self._delete_quantity(row), del_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def _delete_quantity(self, row):
        if 0 <= row < len(self.quantities):
            del self.quantities[row]
            self.refresh_data()
