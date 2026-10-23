# ui/components/line_price_panel.py
import wx
import wx.grid as gridlib

from domain.calculator import Calculator
from domain.cost import CostType
from domain.phase import ToolingBilling
from infrastructure.fx_rate import FxRate

HEADER_BG = wx.Colour(241, 245, 249)
KEY_BG = wx.Colour(248, 250, 252)
ACCENT_TEXT = wx.Colour(30, 64, 175)
LABEL_COLOUR = wx.Colour(100, 116, 139)


def _money(value: float, decimals: int = 2) -> str:
    return f"{value * FxRate.factor():,.{decimals}f}".replace(",", " ")      # montants en devise d'affichage


def _duration(hours: float) -> str:
    if hours <= 0:
        return "—"
    if hours >= 1:
        return f"{hours:.2f} h"
    return f"{hours * 60:.1f} min"


class LinePricePanel(wx.Panel):
    """Analyse de prix en lecture seule, par quantité, pour la sélection du tarif.

    Sélection possible : une ligne de coût, le sous-total d'une opération ou le
    total du projet. Pour chaque quantité de la version : temps de réalisation,
    taux horaire final, coût de revient, prix de vente, coefficient volume,
    chiffre d'affaires et marge. Les achats ajoutent quantité commandée et
    coût du lot fournisseur.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.SetBackgroundColour(wx.WHITE)
        self.project = None
        self._selection = None   # ("cost", cost, op) | ("op", op) | ("project",)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.title = wx.StaticText(self, label="")
        self.title.SetFont(wx.Font(wx.FontInfo(11).FaceName("Segoe UI").Bold()))
        sizer.Add(self.title, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.subtitle = wx.StaticText(self, label="")
        self.subtitle.SetForegroundColour(LABEL_COLOUR)
        sizer.Add(self.subtitle, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.grid = gridlib.Grid(self)
        self.grid.CreateGrid(0, 2)
        self.grid.SetRowLabelSize(0)
        self.grid.EnableEditing(False)
        self.grid.DisableDragRowSize()
        self.grid.SetColLabelSize(26)
        self.grid.SetFont(wx.Font(wx.FontInfo(9).FaceName("Segoe UI")))
        self.grid.SetMinSize((60, 200))
        sizer.Add(self.grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.note = wx.StaticText(self, label="")
        self.note.SetForegroundColour(LABEL_COLOUR)
        sizer.Add(self.note, 0, wx.ALL, 10)
        self.SetSizer(sizer)
        self.clear()

    # ------------------------------------------------------------------ sélection

    def clear(self):
        self._selection = None
        self.title.SetLabel("")
        self.subtitle.SetLabel("")
        self.note.SetLabel("")
        self._reset_grid(0, 0)
        self.Layout()

    def load_cost(self, cost, op, project):
        self.project = project
        self._selection = ("cost", cost, op)
        self.refresh()

    def load_operation(self, op, project):
        self.project = project
        self._selection = ("op", op)
        self.refresh()

    def load_project(self, project):
        self.project = project
        self._selection = ("project",)
        self.refresh()

    def refresh(self):
        """Recalcule la sélection courante (les données ont pu changer dans un autre onglet)."""
        sel, project = self._selection, self.project
        if not sel or project is None:
            return
        quantities = sorted(project.sale_quantities)
        if sel[0] == "cost":
            _, cost, op = sel
            if cost.cost_type == CostType.TOOLING or getattr(cost, "supplier_parent", None):
                self._show_tooling(cost, op, quantities)
                return
            self.title.SetLabel(cost.name)
            self.subtitle.SetLabel(f"Ligne de l'opération « {op.label} »")
            self._show_costs([cost], op, quantities)
        elif sel[0] == "op":
            op = sel[1]
            op.refresh_free_pieces()
            self.title.SetLabel(f"Opération « {op.label} »")
            self.subtitle.SetLabel("Somme des lignes chiffrées de l'opération")
            self._show_costs(op._get_active_costs(), op, quantities)
        else:
            costs = []
            for op in project.operations:
                op.refresh_free_pieces()
                costs.extend(op._get_active_costs())
            self.title.SetLabel("Total du projet")
            self.subtitle.SetLabel(f"Toutes les opérations de la version — {project.current_version.describe()}")
            self._show_costs(costs, None, quantities)

    # ------------------------------------------------------------------ calcul

    def _rate(self, q):
        version = self.project.current_version
        return 1.0 if version.is_serie else float(self.project.volume_margin_rates.get(q, 1.0))

    def _show_costs(self, costs, op, quantities):
        if op is not None:
            op.refresh_free_pieces()
        results = {q: [(c, Calculator.calculate_item(c, q)) for c in costs] for q in quantities}
        has_time = any(c.cost_type == CostType.INTERNAL_OPERATION and
                       any(r.internal_time_hours > 0 for _, r in results[q]) for c in costs for q in quantities)
        has_purchase = any(c.cost_type in (CostType.SUBCONTRACTING, CostType.MATERIAL) for c in costs)

        columns = {}
        for q in quantities:
            rate = self._rate(q)
            cost_pc = sum(r.unit_cost_converted for _, r in results[q])
            sale_pc = sum(r.unit_sale_price for _, r in results[q])
            client_pc = sale_pc * rate
            ca = client_pc * q
            margin = (client_pc - cost_pc) * q
            hours = sum(r.internal_time_hours for c, r in results[q] if c.cost_type == CostType.INTERNAL_OPERATION)
            ca_time = sum(r.unit_sale_price * rate * q for c, r in results[q]
                          if c.cost_type == CostType.INTERNAL_OPERATION)
            batch = sum(r.batch_supplier_cost for c, r in results[q]
                        if c.cost_type in (CostType.SUBCONTRACTING, CostType.MATERIAL))
            ordered = [r.quote_qty_ordered for c, r in results[q]
                       if c.cost_type in (CostType.SUBCONTRACTING, CostType.MATERIAL)]
            columns[q] = {
                "hours": hours, "per_piece_s": hours * 3600.0 / q if q else 0.0,
                "hourly": ca_time / hours if hours > 0 else 0.0,
                "cost_pc": cost_pc, "sale_pc": sale_pc, "rate": rate, "client_pc": client_pc,
                "ca": ca, "margin": margin, "margin_pct": margin / ca * 100 if ca else 0.0,
                "batch": batch, "ordered": sum(ordered) if ordered else 0.0,
            }

        rows = []  # (libellé, fonction q -> texte, mise en valeur)
        if has_time:
            rows += [("Temps de réalisation", lambda d: _duration(d["hours"]), False),
                     ("Temps par pièce", lambda d: f"{d['per_piece_s']:.1f} s" if d["hours"] > 0 else "—", False),
                     ("Taux horaire final (€/h)", lambda d: _money(d["hourly"]) if d["hours"] > 0 else "—", True)]
        if has_purchase:
            rows += [("Quantité commandée", lambda d: f"{d['ordered']:g}" if d["ordered"] else "—", False),
                     ("Coût du lot fournisseur (€)", lambda d: _money(d["batch"]), False)]
        rows += [("Coût de revient (€/pc)", lambda d: _money(d["cost_pc"], 3), False),
                 ("Prix de vente (€/pc)", lambda d: _money(d["sale_pc"], 3), False),
                 ("Coefficient volume", lambda d: f"× {d['rate']:.4f}", False),
                 ("Prix client (€/pc)", lambda d: _money(d["client_pc"], 3), True),
                 ("Chiffre d'affaires (€)", lambda d: _money(d["ca"]), True),
                 ("Marge (€)", lambda d: _money(d["margin"]), False),
                 ("Marge (%)", lambda d: f"{d['margin_pct']:.1f} %", False)]

        self._fill(quantities, rows, columns)
        notes = ["Prix de vente avant coefficient volume ; prix client, CA et marge l'incluent."]
        if has_time:
            notes.append("Taux horaire final = CA des lignes de temps ÷ temps de réalisation.")
        self.note.SetLabel("\n".join(notes))
        self.note.Wrap(max(self.GetSize().width - 30, 260))
        self.Layout()

    def _show_tooling(self, cost, op, quantities):
        parent = getattr(cost, "supplier_parent", None)
        tool = cost
        amount = float(tool.pricing.fixed_price or 0.0) if tool.pricing else 0.0
        billing = op._tooling_billing(tool)
        self.title.SetLabel(tool.name)
        self.subtitle.SetLabel(f"Outillage de l'opération « {op.label} »")
        rows = [("Montant (€)", lambda d: _money(amount), True),
                ("Facturation", lambda d: billing.value, False),
                ("Pièces fournies avec l'outil", lambda d: f"{int(tool.tooling_included_pieces or 0)}", False)]
        if billing == ToolingBilling.AMORTIZED and quantities:
            rows.append(("Part dans le prix pièce (€/pc)", lambda d: _money(amount / d["q"], 3) if d.get("q") else "—", False))
        columns = {q: {"q": q} for q in quantities}
        self._fill(quantities, rows, columns)
        self.note.SetLabel("Refacturé : hors prix pièce, bloc OUTILLAGE de l'offre." if billing == ToolingBilling.REINVOICED
                           else "Amorti : réparti dans le prix pièce.")
        self.Layout()

    # ------------------------------------------------------------------ rendu

    def _reset_grid(self, n_rows, n_cols):
        g = self.grid
        g.BeginBatch()
        if g.GetNumberRows():
            g.DeleteRows(0, g.GetNumberRows())
        want = max(n_cols, 2)
        if g.GetNumberCols() < want:
            g.AppendCols(want - g.GetNumberCols())
        elif g.GetNumberCols() > want:
            g.DeleteCols(want, g.GetNumberCols() - want)
        if n_rows:
            g.AppendRows(n_rows)
        g.EndBatch()

    def _fill(self, quantities, rows, columns):
        g = self.grid
        sym = FxRate.symbol()
        rows = [(label.replace("(€", f"({sym}") if "(€" in label else label, fn, strong) for label, fn, strong in rows]

        self._reset_grid(len(rows), 1 + len(quantities))
        g.BeginBatch()
        g.SetColLabelValue(0, "Quantité")
        for i, q in enumerate(quantities):
            g.SetColLabelValue(1 + i, f"{q}")
        bold = wx.Font(wx.FontInfo(9).FaceName("Segoe UI").Bold())
        for r, (label, fn, strong) in enumerate(rows):
            g.SetCellValue(r, 0, label)
            g.SetCellBackgroundColour(r, 0, KEY_BG)
            if strong:
                g.SetCellFont(r, 0, bold)
            for i, q in enumerate(quantities):
                g.SetCellValue(r, 1 + i, fn(columns[q]))
                g.SetCellAlignment(r, 1 + i, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
                if strong:
                    g.SetCellFont(r, 1 + i, bold)
                    g.SetCellTextColour(r, 1 + i, ACCENT_TEXT)
        g.AutoSizeColumns()
        g.SetColSize(0, max(g.GetColSize(0), 190))
        g.EndBatch()
