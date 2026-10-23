# ui/components/step_summary_panel.py
import wx
import wx.grid as gridlib

from domain.calculator import Calculator
from domain.cost import CostType

HEADER_BG = wx.Colour(241, 245, 249)
TOTAL_BG = wx.Colour(226, 232, 240)
RECAP_BG = wx.Colour(248, 250, 252)
ACCENT_TEXT = wx.Colour(30, 64, 175)
PURCHASE_TYPES = (CostType.SUBCONTRACTING, CostType.MATERIAL)


def _money(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}".replace(",", " ")


def _duration(hours: float) -> str:
    return f"{hours:.2f} h" if hours >= 1 else f"{hours * 60:.1f} min"


class StepSummaryPanel(wx.Panel):
    """Récapitulatif par quantité d'une opération.

    Haut : prix de vente de chaque étape (€ / pièce) et prix de l'opération, avec la
    part de chaque étape à la plus grande quantité. Bas : récapitulatif du lot pour
    chaque quantité — temps de réalisation, vente horaire, achats et marge, chiffre
    d'affaires du lot. Lecture seule, recalculé à chaque modification.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.op = None
        self.project = None
        self.SetBackgroundColour(wx.WHITE)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.title = wx.StaticText(self, label="RÉCAPITULATIF PAR QUANTITÉ")
        self.title.SetFont(wx.Font(wx.FontInfo(9).FaceName("Segoe UI").Bold()))
        self.title.SetForegroundColour(wx.Colour(100, 116, 139))
        sizer.Add(self.title, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 6)

        self.grid = gridlib.Grid(self)
        self.grid.CreateGrid(0, 2)
        self.grid.SetRowLabelSize(0)
        self.grid.EnableEditing(False)
        self.grid.DisableDragRowSize()
        self.grid.SetColLabelSize(26)
        self.grid.SetFont(wx.Font(wx.FontInfo(9).FaceName("Segoe UI")))
        self.grid.SetMinSize((60, 150))   # largeur souple : le tableau défile dans son cadre
        sizer.Add(self.grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        self.note = wx.StaticText(self, label="")
        self.note.SetForegroundColour(wx.Colour(100, 116, 139))
        sizer.Add(self.note, 0, wx.ALL, 6)
        self.SetSizer(sizer)

    def load(self, op, project):
        self.op = op
        self.project = project
        self.refresh()

    def refresh(self):
        grid = self.grid
        grid.BeginBatch()
        try:
            if grid.GetNumberRows():
                grid.DeleteRows(0, grid.GetNumberRows())
            op, project = self.op, self.project
            if op is None or project is None:
                self.note.SetLabel("")
                return
            quantities = sorted(project.sale_quantities)
            op.refresh_free_pieces()
            costs = op._get_active_costs()
            results = {q: {id(c): Calculator.calculate_item(c, q) for c in costs} for q in quantities}

            n_cols = 1 + len(quantities) + 1
            if grid.GetNumberCols() < n_cols:
                grid.AppendCols(n_cols - grid.GetNumberCols())
            elif grid.GetNumberCols() > n_cols:
                grid.DeleteCols(n_cols, grid.GetNumberCols() - n_cols)
            grid.SetColLabelValue(0, "Étape")
            for i, q in enumerate(quantities):
                grid.SetColLabelValue(1 + i, f"Q {q}")
            grid.SetColLabelValue(n_cols - 1, "Part")

            bold = wx.Font(wx.FontInfo(9).FaceName("Segoe UI").Bold())
            totals = [op.total_with_margins(q) for q in quantities]
            ref_total = totals[-1] if totals else 0.0

            def add_row(label, values, share="", background=None, strong=False, colour=None):
                row = grid.GetNumberRows()
                grid.AppendRows(1)
                grid.SetCellValue(row, 0, label)
                for i, value in enumerate(values):
                    grid.SetCellValue(row, 1 + i, value)
                    grid.SetCellAlignment(row, 1 + i, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
                    if colour is not None:
                        grid.SetCellTextColour(row, 1 + i, colour)
                grid.SetCellValue(row, n_cols - 1, share)
                grid.SetCellAlignment(row, n_cols - 1, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
                for col in range(n_cols):
                    if background is not None:
                        grid.SetCellBackgroundColour(row, col, background)
                    if strong:
                        grid.SetCellFont(row, col, bold)

            # --- prix de vente de chaque étape (€ / pièce) ---
            for cost in costs:
                values = [_money(results[q][id(cost)].unit_sale_price) for q in quantities]
                last = results[quantities[-1]][id(cost)].unit_sale_price if quantities else 0.0
                share = f"{last / ref_total * 100:.0f} %" if ref_total else "—"
                label = cost.name + ("  (amorti)" if cost.cost_type == CostType.TOOLING else "")
                add_row(label, values, share)
            add_row("PRIX DE L'OPÉRATION (€/pc)", [_money(t) for t in totals], "100 %" if ref_total else "—",
                    background=TOTAL_BG, strong=True, colour=ACCENT_TEXT)

            # --- récapitulatif du lot, par quantité (ex-« simulation » du résumé) ---
            hours = [sum(r.internal_time_hours for c, r in ((c, results[q][id(c)]) for c in costs)
                         if c.cost_type == CostType.INTERNAL_OPERATION) for q in quantities]
            ca_time = [sum(results[q][id(c)].unit_sale_price * q for c in costs
                           if c.cost_type == CostType.INTERNAL_OPERATION) for q in quantities]
            purchase_cost = [sum(results[q][id(c)].batch_supplier_cost for c in costs if c.cost_type in PURCHASE_TYPES)
                             for q in quantities]
            purchase_sales = [sum(results[q][id(c)].unit_sale_price * q for c in costs if c.cost_type in PURCHASE_TYPES)
                              for q in quantities]
            if any(h > 0 for h in hours):
                add_row("Temps de réalisation", [_duration(h) if h > 0 else "—" for h in hours], background=RECAP_BG)
                add_row("Vente horaire (€/h)", [_money(ca / h) if h > 0 else "—" for ca, h in zip(ca_time, hours)],
                        background=RECAP_BG)
            if any(c > 0 for c in purchase_cost):
                add_row("Achats du lot (€)", [_money(c) for c in purchase_cost], background=RECAP_BG)
                add_row("Marge achats", [f"{(s - c) / s * 100:.1f} %" if s > 0 else "—"
                                         for c, s in zip(purchase_cost, purchase_sales)], background=RECAP_BG)
            add_row("CA du lot (€)", [_money(t * q) for t, q in zip(totals, quantities)],
                    background=TOTAL_BG, strong=True, colour=ACCENT_TEXT)

            grid.AutoSizeColumns()
            grid.SetColSize(0, max(grid.GetColSize(0), 190))

            tooling = sum(float(t.pricing.fixed_price or 0.0) for t in op.get_reinvoiced_tooling_costs() if t.pricing)
            lines = ["Prix de vente avant coefficient de marge volume du tarif."]
            if project.current_version.is_serie:
                lines[0] = "Décomposé : prix indicatif au volume annuel."
            if tooling > 0:
                lines.append(f"Outillage refacturé séparément (hors prix pièce) : {_money(tooling, 0)} €")
            self.note.SetLabel("\n".join(lines))
        finally:
            grid.EndBatch()
        self.Layout()
