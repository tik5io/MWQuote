# ui/components/offer_info_panel.py
import wx
import wx.grid as gridlib

from domain.calculator import Calculator
from domain.cost import CostType, PricingType

PURCHASE_TYPES = (CostType.SUBCONTRACTING, CostType.MATERIAL)
LABEL_COLOUR = wx.Colour(100, 116, 139)
WARN_COLOUR = wx.Colour(180, 90, 0)


class OfferInfoPanel(wx.Panel):
    """Aperçu d'une opération en sous-traitance : informations de l'offre retenue.

    Remplace le résumé « temps / vente horaire » des opérations internes. Affiche
    le fournisseur, la tarification, le lot minimum, la consommation, les
    documents, l'outillage rattaché, puis le prix par pièce pour chaque quantité
    de la version.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.SetBackgroundColour(wx.Colour(250, 252, 255))
        self.op = None
        self.project = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.title = wx.StaticText(self, label="OFFRE RETENUE")
        self.title.SetFont(wx.Font(wx.FontInfo(10).FaceName("Segoe UI").Bold()))
        self.title.SetForegroundColour(wx.Colour(50, 50, 100))
        sizer.Add(self.title, 0, wx.ALL, 10)

        self.warning = wx.StaticText(self, label="")
        self.warning.SetForegroundColour(WARN_COLOUR)
        sizer.Add(self.warning, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.facts = wx.FlexGridSizer(cols=2, hgap=14, vgap=4)
        self.facts.AddGrowableCol(1, 1)
        sizer.Add(self.facts, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.grid = gridlib.Grid(self)
        self.grid.CreateGrid(0, 5)
        for col, label in enumerate(["Qté", "Achat €/pc", "Vente €/pc", "CA du lot (€)", "Qté commandée"]):
            self.grid.SetColLabelValue(col, label)
        self.grid.SetRowLabelSize(0)
        self.grid.EnableEditing(False)
        self.grid.SetMinSize((60, 90))
        sizer.Add(self.grid, 0, wx.EXPAND | wx.ALL, 10)

        self.others = wx.StaticText(self, label="")
        self.others.SetForegroundColour(LABEL_COLOUR)
        sizer.Add(self.others, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(sizer)

    # ------------------------------------------------------------------ données

    @staticmethod
    def retained_offers(op):
        """Lignes d'achat retenues (actives) de l'opération."""
        return [c for c in op.costs.values() if c.cost_type in PURCHASE_TYPES and c.is_active]

    def _fact(self, label, value):
        lbl = wx.StaticText(self, label=label)
        lbl.SetForegroundColour(LABEL_COLOUR)
        self.facts.Add(lbl, 0, wx.ALIGN_TOP)
        val = wx.StaticText(self, label=value)
        val.Wrap(280)
        self.facts.Add(val, 1, wx.EXPAND)

    def load(self, op, project):
        self.op, self.project = op, project
        self.refresh()

    def refresh(self):
        self.Freeze()
        try:
            self.facts.Clear(True)
            if self.grid.GetNumberRows():
                self.grid.DeleteRows(0, self.grid.GetNumberRows())
            op, project = self.op, self.project
            if op is None or project is None:
                return
            offers = self.retained_offers(op)
            all_offers = [c for c in op.costs.values() if c.cost_type in PURCHASE_TYPES]
            if not offers:
                self.title.SetLabel("OFFRE RETENUE")
                self.warning.SetLabel("⚠ Aucune offre retenue : ajoutez une offre (« Nouvelle offre ») "
                                      "ou activez-en une.")
                self.others.SetLabel("")
                return
            cost = offers[0]
            op.refresh_free_pieces()
            self.title.SetLabel(f"OFFRE RETENUE : {cost.name.upper()}")
            self.warning.SetLabel("⚠ Plusieurs offres sont actives : seule la première est détaillée ici."
                                  if len(offers) > 1 else "")
            pricing = cost.pricing
            unit = (pricing.unit if pricing and pricing.unit else "unité")

            self._fact("Réf. offre", cost.supplier_quote_ref or "—")
            if pricing is not None:
                self._fact("Tarification", pricing.pricing_type.value)
                self._fact("Frais fixes", f"{pricing.fixed_price:,.2f} €".replace(",", " "))
                if pricing.pricing_type == PricingType.TIERED and pricing.tiers:
                    tiers = "  ·  ".join(f"≥ {t.min_quantity} : {t.unit_price:,.2f} €".replace(",", " ")
                                         for t in sorted(pricing.tiers, key=lambda t: t.min_quantity))
                    self._fact("Échelons", tiers)
                else:
                    self._fact("Prix unitaire", f"{pricing.unit_price:,.2f} € / {unit}".replace(",", " "))
            moq = cost.get_moq()
            if moq:
                self._fact("Lot minimum (MOQ)", f"{moq} {unit}")
            conso = cost.quantity_per_piece or 1.0
            self._fact("Consommation", f"{conso:g} pièce / {unit}" if cost.quantity_per_piece_is_inverse
                       else f"{conso:g} {unit} / pièce")
            self._fact("Marge", f"{cost.margin_rate:.1f} %")
            if cost.documents:
                self._fact("Documents", ", ".join(d.filename for d in cost.documents))
            tools = [t for t in op.costs.values() if t.cost_type == CostType.TOOLING
                     and t.linked_offer in (None, "", cost.name)]
            if tools:
                amount = sum(float(t.pricing.fixed_price or 0.0) for t in tools if t.pricing)
                free = op.free_pieces_for(cost)
                text = f"{amount:,.0f} €".replace(",", " ")
                if free:
                    text += f" · {free} pièces fournies avec l'outil"
                self._fact("Outillage", text)
            if cost.comment:
                self._fact("Commentaire", cost.comment.strip())

            quantities = sorted(project.sale_quantities)
            for q in quantities:
                res = Calculator.calculate_item(cost, q)
                row = self.grid.GetNumberRows()
                self.grid.AppendRows(1)
                values = [str(q), f"{res.unit_cost_converted:,.2f}".replace(",", " "),
                          f"{res.unit_sale_price:,.2f}".replace(",", " "),
                          f"{res.unit_sale_price * q:,.2f}".replace(",", " "),
                          f"{res.quote_qty_ordered:g} {unit}"]
                for col, value in enumerate(values):
                    self.grid.SetCellValue(row, col, value)
                    self.grid.SetCellAlignment(row, col, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            self.grid.AutoSizeColumns()
            n_other = len(all_offers) - len(offers)
            self.others.SetLabel(f"{n_other} autre(s) offre(s) archivée(s) : voir la comparaison ci-dessous."
                                 if n_other > 0 else "")
        finally:
            self.Thaw()
            self.Layout()
            parent = self.GetParent()
            if parent:
                parent.Layout()
