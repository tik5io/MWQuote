# ui/panels/operation_editor_panel.py
import wx
import wx.grid as gridlib
from domain.operation import Operation

class OperationEditorPanel(wx.Panel):


    def __init__(self, parent):
        super().__init__(parent)
        self.operation = None
        self.on_operation_updated = None
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        self.title = wx.StaticText(self, label="Édition de l'opération")
        main_sizer.Add(self.title, 0, wx.ALL, 5)

        self.grid = gridlib.Grid(self)
        self.grid.CreateGrid(0, 3)

        self.grid.SetColLabelValue(0, "Poste")
        self.grid.SetColLabelValue(1, "Valeur")
        self.grid.SetColLabelValue(2, "Commentaire")

        self.grid.Bind(gridlib.EVT_GRID_CELL_CHANGED, self.on_cell_changed)

        main_sizer.Add(self.grid, 1, wx.EXPAND | wx.ALL, 5)

        self.total_lbl = wx.StaticText(self, label="Total : 0.00")
        main_sizer.Add(self.total_lbl, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

        self.SetSizer(main_sizer)

    def load_operation(self, operation):
        self.operation = operation
        self.title.SetLabel(f"Édition – {operation.code} | {operation.label}")

        self.grid.ClearGrid()
        if self.grid.GetNumberRows() > 0:
            self.grid.DeleteRows(0, self.grid.GetNumberRows())

        for cost in operation.costs.values():
            row = self.grid.GetNumberRows()
            self.grid.AppendRows(1)
            self.grid.SetCellValue(row, 0, cost.name)
            self.grid.SetCellValue(row, 1, str(cost.value))
            self.grid.SetCellValue(row, 2, cost.comment or "")
            self.grid.SetReadOnly(row, 0, True)

        self._update_total()

    def _update_total(self):
        if self.operation:
            total = self.operation.total_cost()
            self.total_lbl.SetLabel(f"Total : {total:.2f}")
        else:
            self.total_lbl.SetLabel("Total : 0.00")

    def on_cell_changed(self, event):
        if not self.operation:
            return

        row = event.GetRow()
        col = event.GetCol()
        cost_name = self.grid.GetCellValue(row, 0)

        if col == 1:
            try:
                value = float(self.grid.GetCellValue(row, col))
                self.operation.update_cost(cost_name, value)
                self._update_total()

                if self.on_operation_updated:
                    self.on_operation_updated(self.operation)

            except ValueError:
                wx.MessageBox("Valeur numérique invalide", "Erreur")
