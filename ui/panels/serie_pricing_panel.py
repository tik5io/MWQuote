# ui/panels/serie_pricing_panel.py
import dataclasses
import wx
import wx.grid as gridlib
from domain.project import Project
from domain.serie_data import SerieData, CapexItem, ToolingItem, MachinePost, SeriePurchaseItem
from domain.cost import CostType
from domain.operation import SUBCONTRACTING_TYPOLOGY, TOOLING_TYPOLOGY
from ui.components.serie_sensitivity_panel import _eur
from ui.components.serie_analysis_charts import PriceDecompositionBar, CapacityBottleneckChart, COST_COLOURS
from ui.components.ribbon_button import RibbonButton, TOOLING


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(v, decimals=4):
    if v is None:
        return "-"
    try:
        return f"{v:,.{decimals}f}".replace(",", " ")
    except Exception:
        return str(v)


def _pct(v):
    if v is None:
        return "-"
    return f"{v * 100:.1f} %"


SECTION_BG = wx.Colour(30, 90, 160)
SECTION_FG = wx.Colour(255, 255, 255)
RESULT_BG  = wx.Colour(255, 255, 180)
WARN_BG    = wx.Colour(255, 200, 180)
OK_BG      = wx.Colour(180, 240, 180)
TOTAL_BG   = wx.Colour(200, 220, 255)


# ---------------------------------------------------------------------------
# Dialogs édition items
# ---------------------------------------------------------------------------

class CapexDialog(wx.Dialog):
    def __init__(self, parent, item: CapexItem = None):
        super().__init__(parent, title="CAPEX – Équipement", size=(440, 300))
        item = item or CapexItem()
        self._src = item
        sizer = wx.BoxSizer(wx.VERTICAL)

        if item.operation_code:
            hint = wx.StaticText(self, label="Ligne machine liée à une opération : désignation et nombre de\n"
                                             "machines sont pilotés par la liste des opérations (ici en lecture seule).")
            hint.SetForegroundColour(wx.Colour(120, 90, 0))
            sizer.Add(hint, 0, wx.ALL, 10)

        fg = wx.FlexGridSizer(5, 2, 8, 12)
        fg.AddGrowableCol(1, 1)

        self.name   = self._row(fg, "Désignation",                  wx.TextCtrl(self, value=item.name))
        self.nmach  = self._row(fg, "Nb machines",                  wx.SpinCtrl(self, min=1, max=50,
                                                                                initial=max(item.machines_count, 1)))
        self.cost   = self._row(fg, "Coût d'achat unitaire (€)",    wx.TextCtrl(self, value=str(item.cost)))
        self.resid  = self._row(fg, "Valeur résiduelle unit. (€)",  wx.TextCtrl(self, value=str(item.residual_value)))
        self.margin = self._row(fg, "Marge MW (%)",                 wx.SpinCtrlDouble(self, min=0, max=100,
                                                                                initial=item.margin_rate * 100, inc=1))
        if item.operation_code:
            self.name.Enable(False)
            self.nmach.Enable(False)

        sizer.Add(fg, 1, wx.EXPAND | wx.ALL, 14)
        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(sizer)

    def _row(self, fg, label, ctrl):
        fg.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        fg.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    def get_item(self) -> CapexItem:
        return CapexItem(
            name=self.name.GetValue().strip() or "CAPEX",
            cost=float(self.cost.GetValue().replace(",", ".") or 0),
            residual_value=float(self.resid.GetValue().replace(",", ".") or 0),
            margin_rate=self.margin.GetValue() / 100.0,
            operation_code=self._src.operation_code,
            machines_count=self.nmach.GetValue(),
        )


class ToolingDialog(wx.Dialog):
    def __init__(self, parent, item: ToolingItem = None):
        super().__init__(parent, title="Tooling – Outillage", size=(420, 240))
        item = item or ToolingItem()
        sizer = wx.BoxSizer(wx.VERTICAL)
        fg = wx.FlexGridSizer(4, 2, 8, 12)
        fg.AddGrowableCol(1, 1)

        self.name   = self._row(fg, "Désignation",        wx.TextCtrl(self, value=item.name))
        self.cost   = self._row(fg, "Coût (€)",           wx.TextCtrl(self, value=str(item.cost)))
        self.life   = self._row(fg, "Durée de vie (pcs)", wx.TextCtrl(self, value=str(item.lifetime_pieces)))
        self.margin = self._row(fg, "Marge MW (%)",       wx.SpinCtrlDouble(self, min=0, max=100,
                                                                            initial=item.margin_rate * 100, inc=1))

        sizer.Add(fg, 1, wx.EXPAND | wx.ALL, 14)
        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(sizer)

    def _row(self, fg, label, ctrl):
        fg.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        fg.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    def get_item(self) -> ToolingItem:
        return ToolingItem(
            name=self.name.GetValue().strip() or "Outillage",
            cost=float(self.cost.GetValue().replace(",", ".") or 0),
            lifetime_pieces=max(1, int(self.life.GetValue().replace(" ", "") or 1)),
            margin_rate=self.margin.GetValue() / 100.0,
        )


class SeriePurchaseDialog(wx.Dialog):
    """Édition d'une ligne d'achat série (« achat opération »).

    Trois modes de calcul du prix / pièce : unitaire, au mètre (€/m × longueur),
    ou forfait au lot (€/lot ÷ taille de lot).
    """

    MODES = [("Unitaire (€/pièce)", "unit"),
             ("Au mètre (€/m × longueur/pièce)", "length"),
             ("Forfait au lot (€/lot ÷ taille de lot)", "lot")]

    def __init__(self, parent, item: SeriePurchaseItem = None):
        super().__init__(parent, title="Achat série", size=(470, 420))
        item = item or SeriePurchaseItem()
        self._src = item
        sizer = wx.BoxSizer(wx.VERTICAL)

        if item.needs_edit:
            hint = wx.StaticText(self, label="Prix repris de la gamme indéterminé pour le volume série.\n"
                                             "Choisir le mode et saisir le prix d'achat série.")
            hint.SetForegroundColour(wx.Colour(190, 60, 30))
            sizer.Add(hint, 0, wx.ALL, 10)

        fg = wx.FlexGridSizer(8, 2, 8, 12)
        fg.AddGrowableCol(1, 1)
        self.name = self._row(fg, "Désignation", wx.TextCtrl(self, value=item.name))

        self.mode = wx.Choice(self, choices=[lbl for lbl, _ in self.MODES])
        self.mode.SetSelection(max(0, [c for _, c in self.MODES].index(item.mode)
                                   if item.mode in [c for _, c in self.MODES] else 0))
        self._row(fg, "Mode de calcul", self.mode)

        self.unit     = self._row(fg, "Prix unitaire (€/pièce)",  wx.TextCtrl(self, value=str(item.unit_price)))
        self.permeter = self._row(fg, "Prix au mètre (€/m)",      wx.TextCtrl(self, value=str(item.price_per_meter)))
        self.length   = self._row(fg, "Longueur / pièce (m)",     wx.TextCtrl(self, value=str(item.length_per_piece_m)))
        self.lotamt   = self._row(fg, "Forfait au lot (€/lot)",   wx.TextCtrl(self, value=str(item.lot_amount)))
        self.lotsize  = self._row(fg, "Taille de lot (pièces)",   wx.TextCtrl(self, value=str(item.lot_size)))
        self.margin   = self._row(fg, "Marge (%)", wx.SpinCtrlDouble(self, min=0, max=100,
                                                                     initial=item.margin_rate * 100, inc=1))
        sizer.Add(fg, 0, wx.EXPAND | wx.ALL, 14)

        self._lbl_pp = wx.StaticText(self, label="")
        f = self._lbl_pp.GetFont(); f.SetWeight(wx.FONTWEIGHT_BOLD); self._lbl_pp.SetFont(f)
        sizer.Add(self._lbl_pp, 0, wx.LEFT | wx.BOTTOM, 16)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(sizer)

        self.mode.Bind(wx.EVT_CHOICE, lambda e: self._sync())
        for c in (self.unit, self.permeter, self.length, self.lotamt, self.lotsize):
            c.Bind(wx.EVT_TEXT, lambda e: self._sync())
        self._sync()

    def _row(self, fg, label, ctrl):
        fg.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        fg.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    def _mode_code(self) -> str:
        return self.MODES[self.mode.GetSelection()][1]

    def _sync(self):
        """Active les champs du mode choisi et met à jour l'aperçu €/pièce."""
        mode = self._mode_code()
        self.unit.Enable(mode == "unit")
        self.permeter.Enable(mode == "length")
        self.length.Enable(mode == "length")
        self.lotamt.Enable(mode == "lot")
        self.lotsize.Enable(mode == "lot")
        self._lbl_pp.SetLabel(f"→ Prix d'achat : {self._build().per_piece_cost():.2f} €/pièce")

    def _f(self, ctrl, default=0.0):
        try:
            return float(ctrl.GetValue().replace(",", ".").replace(" ", ""))
        except Exception:
            return default

    def _build(self) -> SeriePurchaseItem:
        return SeriePurchaseItem(
            name=self.name.GetValue().strip() or "Achat",
            mode=self._mode_code(),
            unit_price=self._f(self.unit),
            price_per_meter=self._f(self.permeter),
            length_per_piece_m=self._f(self.length),
            lot_amount=self._f(self.lotamt),
            lot_size=max(1, int(self._f(self.lotsize, 1))),
            margin_rate=self.margin.GetValue() / 100.0,
            operation_code=self._src.operation_code,
        )

    def get_item(self) -> SeriePurchaseItem:
        it = self._build()
        it.needs_edit = self._src.needs_edit and it.per_piece_cost() <= 0   # résolu dès qu'un prix est saisi
        return it


class MachinePostDialog(wx.Dialog):
    """Dialogue de saisie uniquement du nombre de machines. TC et TH sont en lecture seule."""

    def __init__(self, parent, item: MachinePost):
        super().__init__(parent, title="Poste machine – Nb machines disponibles", size=(420, 260))
        sizer = wx.BoxSizer(wx.VERTICAL)
        fg = wx.FlexGridSizer(4, 2, 8, 12)
        fg.AddGrowableCol(1, 1)

        def ro_text(val):
            ctrl = wx.TextCtrl(self, value=str(val), style=wx.TE_READONLY)
            ctrl.SetBackgroundColour(wx.Colour(240, 240, 240))
            return ctrl

        fg.Add(wx.StaticText(self, label="Opération"), 0, wx.ALIGN_CENTER_VERTICAL)
        fg.Add(ro_text(item.name), 1, wx.EXPAND)

        fg.Add(wx.StaticText(self, label="TC (s/pcs, dérivé)"), 0, wx.ALIGN_CENTER_VERTICAL)
        fg.Add(ro_text(f"{item.cycle_time_s:.2f}"), 1, wx.EXPAND)

        fg.Add(wx.StaticText(self, label="TH moyen (€/h, dérivé)"), 0, wx.ALIGN_CENTER_VERTICAL)
        fg.Add(ro_text(f"{item.mo_rate_euro_per_h:.2f}"), 1, wx.EXPAND)

        fg.Add(wx.StaticText(self, label="Nb machines disponibles"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.nmach = wx.SpinCtrl(self, min=1, max=20, initial=item.machines_available)
        fg.Add(self.nmach, 0, wx.EXPAND)

        sizer.Add(fg, 1, wx.EXPAND | wx.ALL, 14)
        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(sizer)

    def get_machines_available(self) -> int:
        return self.nmach.GetValue()


# ---------------------------------------------------------------------------
# Reusable table widget (ListCtrl + Add/Edit/Delete toolbar)
# ---------------------------------------------------------------------------

class ItemTable(wx.Panel):
    """Generic ListCtrl panel with add/edit/delete buttons."""

    def __init__(self, parent, columns, on_change=None):
        super().__init__(parent)
        self.on_change = on_change
        self._dialog_class = None
        self._items = []

        sizer = wx.BoxSizer(wx.VERTICAL)

        # Toolbar
        tb = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add  = wx.Button(self, label="+  Ajouter", size=(90, 26))
        self.btn_edit = wx.Button(self, label="Modifier",   size=(80, 26))
        self.btn_del  = wx.Button(self, label="Supprimer",  size=(90, 26))
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            tb.Add(b, 0, wx.RIGHT, 4)
        sizer.Add(tb, 0, wx.TOP | wx.BOTTOM, 4)

        # ListCtrl
        self.lc = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SIMPLE)
        for i, (col, w) in enumerate(columns):
            self.lc.InsertColumn(i, col, width=w)
        sizer.Add(self.lc, 1, wx.EXPAND)

        self.SetSizer(sizer)

        self.btn_add.Bind(wx.EVT_BUTTON, self._on_add)
        self.btn_edit.Bind(wx.EVT_BUTTON, self._on_edit)
        self.btn_del.Bind(wx.EVT_BUTTON, self._on_del)
        self.lc.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit)

    def set_dialog_class(self, cls):
        self._dialog_class = cls

    def set_items(self, items):
        self._items = list(items)
        self._refresh_lc()
        self._autosize_height()

    def _autosize_height(self):
        """Hauteur de la liste adaptée au nombre de lignes (pour tout lire sans scroll interne)."""
        row_h = 21
        n = max(len(self._items), 1)
        h = min(28 + n * row_h + 6, 520)
        self.lc.SetMinSize((-1, h))
        self.Layout()
        parent = self.GetParent()
        if parent is not None:
            parent.Layout()

    def get_items(self):
        return list(self._items)

    def _refresh_lc(self):
        self.lc.DeleteAllItems()
        for item in self._items:
            self._append_row(item)

    def _append_row(self, item):
        raise NotImplementedError

    def _on_add(self, _):
        dlg = self._dialog_class(self)
        if dlg.ShowModal() == wx.ID_OK:
            self._items.append(dlg.get_item())
            self._refresh_lc()
            if self.on_change:
                self.on_change()
        dlg.Destroy()

    def _on_edit(self, _):
        idx = self.lc.GetFirstSelected()
        if idx < 0:
            return
        dlg = self._dialog_class(self, self._items[idx])
        if dlg.ShowModal() == wx.ID_OK:
            self._items[idx] = dlg.get_item()
            self._refresh_lc()
            if self.on_change:
                self.on_change()
        dlg.Destroy()

    def _on_del(self, _):
        idx = self.lc.GetFirstSelected()
        if idx < 0:
            return
        del self._items[idx]
        self._refresh_lc()
        if self.on_change:
            self.on_change()


class CapexTable(ItemTable):
    COLS = [("Désignation", 190), ("Mach.", 55), ("Coût €/u", 90), ("Résiduel €", 80),
            ("Marge", 55), ("Amort/an €", 90), ("Prix/pc €", 100)]

    def __init__(self, parent, on_change=None, serie_ref=None):
        super().__init__(parent, self.COLS, on_change)
        self.set_dialog_class(CapexDialog)
        self._serie_ref = serie_ref  # callable → SerieData (pour volume et durée amort.)

    def _append_row(self, item: CapexItem):
        sd = self._serie_ref() if self._serie_ref else None
        years = sd.program_lifetime_years if sd and sd.program_lifetime_years > 0 else 1
        vol   = sd.annual_volume if sd and sd.annual_volume > 0 else 1
        amort_an = item.net_investment / years
        cost_pc  = amort_an / vol
        price_pc = cost_pc * (1 + item.margin_rate)
        idx = self.lc.InsertItem(self.lc.GetItemCount(), item.name)
        self.lc.SetItem(idx, 1, str(item.machines_count))
        self.lc.SetItem(idx, 2, f"{item.cost:,.0f}")
        self.lc.SetItem(idx, 3, f"{item.residual_value:,.0f}")
        self.lc.SetItem(idx, 4, f"{item.margin_rate*100:.0f}%")
        self.lc.SetItem(idx, 5, f"{amort_an:,.0f}")
        self.lc.SetItem(idx, 6, f"{price_pc:.2f}")
        if item.operation_code:   # ligne machine liée à une opération
            self.lc.SetItemBackgroundColour(idx, wx.Colour(235, 242, 252))


class ToolingTable(ItemTable):
    COLS = [("Désignation", 170), ("Coût €", 80), ("Durée vie pcs", 100),
            ("Marge", 60), ("Coût/pc €", 90), ("Prix/pc €", 90)]

    def __init__(self, parent, on_change=None):
        super().__init__(parent, self.COLS, on_change)
        self.set_dialog_class(ToolingDialog)

    def _append_row(self, item: ToolingItem):
        cost_pc = (item.cost / item.lifetime_pieces) if item.lifetime_pieces > 0 else 0
        price_pc = cost_pc * (1 + item.margin_rate)
        idx = self.lc.InsertItem(self.lc.GetItemCount(), item.name)
        self.lc.SetItem(idx, 1, f"{item.cost:,.0f}")
        self.lc.SetItem(idx, 2, f"{item.lifetime_pieces:,}")
        self.lc.SetItem(idx, 3, f"{item.margin_rate*100:.0f}%")
        self.lc.SetItem(idx, 4, f"{cost_pc:.2f}")
        self.lc.SetItem(idx, 5, f"{price_pc:.2f}")


class PurchaseTable(ItemTable):
    """Achats série repris de la gamme (sous-traitance / matières), éditables.

    Les lignes « À éditer » (prix repris indéterminé, mis à 0) sont surlignées.
    """

    COLS = [("Achat (origine gamme)", 220), ("Mode", 80), ("Prix achat €/pc", 100),
            ("Marge", 55), ("Prix/pc €", 90), ("État", 80)]
    MODE_LABEL = {"unit": "Unitaire", "length": "Au mètre", "lot": "Forfait lot"}

    def __init__(self, parent, on_change=None):
        super().__init__(parent, self.COLS, on_change)
        self.set_dialog_class(SeriePurchaseDialog)

    def _append_row(self, item: SeriePurchaseItem):
        cpp = item.per_piece_cost()
        price = cpp * (1 + item.margin_rate)
        idx = self.lc.InsertItem(self.lc.GetItemCount(), item.name)
        self.lc.SetItem(idx, 1, self.MODE_LABEL.get(item.mode, "Unitaire"))
        self.lc.SetItem(idx, 2, f"{cpp:.2f}")
        self.lc.SetItem(idx, 3, f"{item.margin_rate*100:.0f}%")
        self.lc.SetItem(idx, 4, f"{price:.2f}")
        self.lc.SetItem(idx, 5, "À éditer" if item.needs_edit else "OK")
        if item.needs_edit:
            self.lc.SetItemBackgroundColour(idx, WARN_BG)


class MachineTable(wx.Panel):
    """Table de postes machine liés aux opérations du projet.

    TC et TH sont dérivés des opérations (lecture seule).
    Seul machines_available est éditable via double-clic.
    Pas de bouton Ajouter/Supprimer : les postes viennent du projet.
    """

    COLS = [("Opération", 180), ("TC s/pc", 80), ("TH €/h", 80), ("Machines", 72),
            ("Cap./équipe", 100), ("Cap./an", 100), ("Charge", 72), ("Statut", 90)]

    def __init__(self, parent, on_change=None, serie_ref=None):
        super().__init__(parent)
        self.on_change = on_change
        self._serie_ref = serie_ref
        self._items = []

        sizer = wx.BoxSizer(wx.VERTICAL)

        # Edit-only toolbar
        tb = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_edit = wx.Button(self, label="Modifier nb machines", size=(160, 26))
        tb.Add(self.btn_edit, 0, wx.RIGHT, 4)
        lbl_hint = wx.StaticText(self, label="(postes synchronisés depuis les Opérations du projet)")
        lbl_hint.SetForegroundColour(wx.Colour(100, 100, 100))
        tb.Add(lbl_hint, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(tb, 0, wx.TOP | wx.BOTTOM, 4)

        self.lc = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SIMPLE)
        for i, (col, w) in enumerate(self.COLS):
            self.lc.InsertColumn(i, col, width=w)
        sizer.Add(self.lc, 1, wx.EXPAND)

        self.SetSizer(sizer)

        self.btn_edit.Bind(wx.EVT_BUTTON, self._on_edit)
        self.lc.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit)

    def set_items(self, items):
        self._items = list(items)
        self._refresh_lc()

    def get_items(self):
        return list(self._items)

    def _refresh_lc(self):
        self.lc.DeleteAllItems()
        for item in self._items:
            self._append_row(item)

    def _append_row(self, item: MachinePost):
        sd = self._serie_ref() if self._serie_ref else None
        cap_eq = cap_an = charge = 0.0
        if sd and item.cycle_time_s > 0:
            cap_eq = item.machines_available * sd.hours_per_shift * 3600 / item.cycle_time_s * sd.trs
            cap_an = cap_eq * sd.shifts_per_day * sd.working_days_per_year
            charge = (sd.annual_volume / cap_an) if cap_an > 0 else 0.0
        statut = "" if item.cycle_time_s <= 0 else ("SURCHARGE" if charge > 0.85 else "OK")

        idx = self.lc.InsertItem(self.lc.GetItemCount(), item.name)
        self.lc.SetItem(idx, 1, f"{item.cycle_time_s:.2f}" if item.cycle_time_s > 0 else "—")
        self.lc.SetItem(idx, 2, f"{item.mo_rate_euro_per_h:.2f}" if item.cycle_time_s > 0 else "—")
        self.lc.SetItem(idx, 3, str(item.machines_available))
        self.lc.SetItem(idx, 4, f"{cap_eq:,.0f}" if item.cycle_time_s > 0 else "—")
        self.lc.SetItem(idx, 5, f"{cap_an:,.0f}" if item.cycle_time_s > 0 else "—")
        self.lc.SetItem(idx, 6, f"{charge*100:.1f}%" if item.cycle_time_s > 0 else "—")
        self.lc.SetItem(idx, 7, statut)
        if statut == "SURCHARGE":
            self.lc.SetItemBackgroundColour(idx, WARN_BG)
        elif statut == "OK":
            self.lc.SetItemBackgroundColour(idx, OK_BG)

    def _on_edit(self, _):
        idx = self.lc.GetFirstSelected()
        if idx < 0:
            return
        item = self._items[idx]
        dlg = MachinePostDialog(self, item)
        if dlg.ShowModal() == wx.ID_OK:
            item.machines_available = dlg.get_machines_available()
            self._refresh_lc()
            if self.on_change:
                self.on_change()
        dlg.Destroy()


# ---------------------------------------------------------------------------
# Opérations : liste fusionnée capacité + sensibilité temps/taux
# ---------------------------------------------------------------------------

class _StepSensRow:
    """Une étape (ligne interne) d'une opération, dépliée dans la grille de sensibilité.

    Mêmes curseurs temps / taux que l'opération, mais agissant sur cette seule étape.
    Le facteur d'une étape se COMBINE (produit) avec celui de son opération : bouger le
    curseur de l'opération met toutes ses étapes à l'échelle, puis chaque étape se règle
    finement par-dessus.
    """

    def __init__(self, parent_row, cost):
        self.parent = parent_row
        self.cost = cost
        self.time_pct = 0
        self.rate_pct = 0
        self.t0_h = cost.serie_time_per_piece_h()     # h / pièce
        self.rate0 = cost.serie_rate()                # €/h

    @property
    def label(self):
        return self.cost.name

    @property
    def tc0_s(self):
        return self.t0_h * 3600.0

    @property
    def time_factor(self):
        """Facteur temps effectif : curseur de l'opération × curseur de l'étape."""
        return (1 + self.parent.time_pct / 100.0) * (1 + self.time_pct / 100.0)

    @property
    def rate_factor(self):
        return (1 + self.parent.rate_pct / 100.0) * (1 + self.rate_pct / 100.0)

    @property
    def tc_sim_s(self):
        return self.tc0_s * self.time_factor

    @property
    def rate_sim(self):
        return self.rate0 * self.rate_factor

    @property
    def moved(self):
        return self.time_pct != 0 or self.rate_pct != 0


class _OpSensRow:
    """Opération interne de la version Série, vue capacité + sensibilité.

    Les valeurs de base (temps par pièce agrégé, taux moyen) sont héritées de la
    gamme via les valeurs Série des lignes internes : elles servent de référence 0
    pour les deux curseurs. Les curseurs de l'opération agissent sur TOUTES ses lignes
    internes (mise à l'échelle proportionnelle) ; l'opération peut se déplier en
    `steps` (une sous-ligne par étape) pour ajuster chaque étape séparément.
    """

    def __init__(self, op):
        self.time_pct = 0
        self.rate_pct = 0
        self.machines = 1
        self.enabled = True
        self.setup_launch_h = 0.0
        self.steps = []
        self.bind(op)

    def bind(self, op):
        """(Re)lie la ligne aux coûts internes de `op` et recalcule les valeurs de base."""
        previous = {s.cost.name: (s.time_pct, s.rate_pct) for s in self.steps}
        self.op = op
        self.costs = [c for c in op.costs.values()
                      if c.cost_type == CostType.INTERNAL_OPERATION and getattr(c, "is_active", True)]
        self.time0_h = sum(c.serie_time_per_piece_h() for c in self.costs)     # h / pièce
        rate_x_time = sum(c.serie_time_per_piece_h() * c.serie_rate() for c in self.costs)
        self.rate0 = (rate_x_time / self.time0_h) if self.time0_h > 0 else 0.0  # €/h moyen pondéré
        # Étapes : les réglages déjà faits survivent à un re-lien sur les lignes « vivantes »
        self.steps = [_StepSensRow(self, c) for c in self.costs]
        for s in self.steps:
            s.time_pct, s.rate_pct = previous.get(s.cost.name, (0, 0))

    @property
    def label(self):
        return self.op.label

    @property
    def tc0_s(self):
        """Temps par pièce agrégé de base (s) — référence 0 des curseurs."""
        return self.time0_h * 3600.0

    @property
    def tc_sim_s(self):
        """Temps simulé agrégé = somme des temps simulés des étapes (opération × étape)."""
        return sum(s.tc_sim_s for s in self.steps)

    @property
    def rate_sim(self):
        """Taux simulé : moyenne des taux simulés des étapes, pondérée par leur temps simulé."""
        weight = sum(s.t0_h * s.time_factor for s in self.steps)
        if weight <= 0:
            return self.rate0 * (1 + self.rate_pct / 100.0)
        return sum(s.t0_h * s.time_factor * s.rate_sim for s in self.steps) / weight

    @property
    def op_moved(self):
        return self.time_pct != 0 or self.rate_pct != 0

    @property
    def moved(self):
        return self.op_moved or any(s.moved for s in self.steps)

    def overrides(self):
        """{id(ligne): {cycle_s, rate}} pour les lignes dont un curseur (opération ou étape) a bougé."""
        out = {}
        for s in self.steps:
            ov = {}
            if self.time_pct or s.time_pct:
                ov["cycle_s"] = s.cost.serie_cycle_s() * s.time_factor
            if self.rate_pct or s.rate_pct:
                ov["rate"] = s.cost.serie_rate() * s.rate_factor
            if ov:
                out[id(s.cost)] = ov
        return out

    def apply(self):
        """Enregistre les valeurs simulées comme valeurs Série des lignes internes."""
        for s in self.steps:
            if self.time_pct or s.time_pct:
                s.cost.serie_cycle_time_s = round(s.cost.serie_cycle_s() * s.time_factor, 3)
            if self.rate_pct or s.rate_pct:
                s.cost.serie_hourly_rate = round(s.cost.serie_rate() * s.rate_factor, 2)


class OperationSensGrid(wx.ScrolledWindow):
    """Grille scrollable : une ligne par opération, curseurs temps/taux intégrés.

    Chaque opération se déplie (▸ / ▾) en une sous-ligne par étape, avec les mêmes curseurs
    temps / taux pour un réglage étape par étape.
    """

    COLS = ["Actif", "Opération", "TC base", "Temps", "TC simulé", "TH base", "Taux", "TH simulé",
            "Machines", "Lancement (h)", "Amort./pc", "Cap./an", "Charge", "Statut"]

    def __init__(self, parent, on_slider=None, on_select=None, on_machines=None,
                 on_enable=None, on_launch=None, on_expand=None):
        super().__init__(parent, style=wx.VSCROLL | wx.HSCROLL | wx.BORDER_THEME)
        self.SetScrollRate(20, 20)
        self.on_slider = on_slider
        self.on_select = on_select
        self.on_machines = on_machines
        self.on_enable = on_enable
        self.on_launch = on_launch
        self.on_expand = on_expand
        self.rows = []
        self.selected = 0
        self._widgets = []
        # Opérations dépliées (par code d'opération) : survit à la reconstruction des lignes
        self.expanded = set()
        self._sub_widgets = {}   # (indice opération, indice étape) -> widgets de la sous-ligne
        self.sizer = wx.FlexGridSizer(cols=len(self.COLS), hgap=8, vgap=4)
        self.sizer.AddGrowableCol(3, 1)   # curseur temps
        self.sizer.AddGrowableCol(6, 1)   # curseur taux
        self.SetSizer(self.sizer)

    def set_rows(self, rows):
        self.rows = rows
        self.selected = min(self.selected, max(len(rows) - 1, 0))
        self._build()

    def _build(self):
        self.Freeze()
        self.sizer.Clear(delete_windows=True)
        self._widgets = []
        self._sub_widgets = {}
        if not self.rows:
            self.sizer.Add(wx.StaticText(self, label="Aucune opération interne dans ce scénario."))
            self.FitInside()
            self.Thaw()
            return
        for text in self.COLS:
            t = wx.StaticText(self, label=text)
            t.SetFont(t.GetFont().Bold())
            self.sizer.Add(t, 0, wx.ALIGN_CENTER_VERTICAL)
        for idx, row in enumerate(self.rows):
            chk = wx.CheckBox(self)
            chk.SetValue(getattr(row, "enabled", True))
            chk.SetToolTip("Décocher pour exclure cette opération du chiffrage série "
                           "(MO, capacité, goulot, CAPEX).")
            chk.Bind(wx.EVT_CHECKBOX, lambda e, i=idx: self._on_enable(i))
            name = wx.StaticText(self, label="  " + row.label, size=(190, -1),
                                 style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
            name.SetToolTip(row.label)
            name.SetCursor(wx.Cursor(wx.CURSOR_HAND))
            name.Bind(wx.EVT_LEFT_DOWN, lambda e, i=idx: self._select(i))
            # Dépliant : affiche une sous-ligne par étape de l'opération (réglage fin étape par étape)
            name_cell = wx.BoxSizer(wx.HORIZONTAL)
            if row.steps:
                is_open = row.op.code in self.expanded
                fold = wx.StaticText(self, label="▾" if is_open else "▸", size=(18, -1),
                                     style=wx.ST_NO_AUTORESIZE | wx.ALIGN_CENTRE_HORIZONTAL)
                fold.SetCursor(wx.Cursor(wx.CURSOR_HAND))
                fold.SetToolTip(f"{'Replier' if is_open else 'Déplier'} les {len(row.steps)} étape(s) de cette opération "
                                "pour ajuster temps et taux étape par étape.")
                fold.Bind(wx.EVT_LEFT_DOWN, lambda e, i=idx: self._toggle(i))
            else:
                fold = wx.StaticText(self, label="", size=(18, -1))
            name_cell.Add(fold, 0, wx.ALIGN_CENTER_VERTICAL)
            name_cell.Add(name, 0, wx.ALIGN_CENTER_VERTICAL)
            tc0 = wx.StaticText(self, label=f"{row.tc0_s:.2f} s" if row.tc0_s > 0 else "—")
            s_tc = wx.Slider(self, value=row.time_pct, minValue=-100, maxValue=100, size=(110, -1))
            tc_sim = wx.StaticText(self, label="", size=(150, -1), style=wx.ST_NO_AUTORESIZE)
            r0 = wx.StaticText(self, label=f"{row.rate0:.0f} €/h" if row.rate0 > 0 else "—")
            s_rate = wx.Slider(self, value=row.rate_pct, minValue=-100, maxValue=100, size=(110, -1))
            r_sim = wx.StaticText(self, label="", size=(120, -1), style=wx.ST_NO_AUTORESIZE)
            mach = wx.SpinCtrl(self, min=1, max=20, initial=row.machines, size=(60, -1))
            launch = wx.SpinCtrlDouble(self, min=0, max=24, inc=0.25,
                                       initial=getattr(row, "setup_launch_h", 0.0), size=(80, -1))
            launch.SetToolTip("Temps de lancement / équipe de cette opération (h), chiffré à son taux horaire.")
            amort = wx.StaticText(self, label="—", size=(80, -1), style=wx.ST_NO_AUTORESIZE)
            amort.SetToolTip("Amortissement machine par pièce (coût saisi dans l'onglet CAPEX & Tooling).")
            cap = wx.StaticText(self, label="—", size=(90, -1), style=wx.ST_NO_AUTORESIZE)
            charge = wx.StaticText(self, label="—", size=(70, -1), style=wx.ST_NO_AUTORESIZE)
            statut = wx.StaticText(self, label="", size=(90, -1), style=wx.ST_NO_AUTORESIZE)
            enabled = getattr(row, "enabled", True)
            if row.tc0_s <= 0 or not enabled:
                s_tc.Enable(False)
            if row.rate0 <= 0 or not enabled:
                s_rate.Enable(False)
            if not enabled:
                mach.Enable(False)
                launch.Enable(False)
                name.SetForegroundColour(wx.Colour(150, 150, 150))
            for wdg in (s_tc, s_rate):
                wdg.Bind(wx.EVT_SLIDER, lambda e, i=idx: self._on_slider(i))
                wdg.Bind(wx.EVT_SET_FOCUS, lambda e, i=idx: (self._select(i), e.Skip()))
            mach.Bind(wx.EVT_SPINCTRL, lambda e, i=idx: self._on_mach(i))
            launch.Bind(wx.EVT_SPINCTRLDOUBLE, lambda e, i=idx: self._on_launch(i))
            for wdg in (chk, name_cell, tc0, s_tc, tc_sim, r0, s_rate, r_sim, mach, launch, amort, cap, charge, statut):
                self.sizer.Add(wdg, 0, wx.ALIGN_CENTER_VERTICAL
                               | (wx.EXPAND if isinstance(wdg, wx.Slider) else 0))
            self._widgets.append(dict(chk=chk, name=name, s_tc=s_tc, tc_sim=tc_sim, s_rate=s_rate,
                                      r_sim=r_sim, mach=mach, launch=launch, amort=amort, cap=cap,
                                      charge=charge, statut=statut))
            if row.op.code in self.expanded:
                self._add_step_rows(idx, row, enabled)
        self.FitInside()
        self.Thaw()
        self.Layout()

    def _add_step_rows(self, i, row, op_enabled):
        """Sous-lignes des étapes d'une opération dépliée : mêmes curseurs temps / taux,
        agissant sur l'étape seule (combinés à ceux de l'opération)."""
        sub_fg = wx.Colour(70, 100, 140)
        for j, step in enumerate(row.steps):
            self.sizer.Add(wx.StaticText(self, label=""), 0)                      # Actif
            name = wx.StaticText(self, label="      ↳ " + step.label, size=(208, -1),
                                 style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
            name.SetToolTip(f"Étape « {step.label} » de l'opération « {row.label} »")
            name.SetForegroundColour(sub_fg)
            tc0 = wx.StaticText(self, label=f"{step.tc0_s:.2f} s" if step.tc0_s > 0 else "—")
            s_tc = wx.Slider(self, value=step.time_pct, minValue=-100, maxValue=100, size=(110, -1))
            tc_sim = wx.StaticText(self, label="", size=(150, -1), style=wx.ST_NO_AUTORESIZE)
            r0 = wx.StaticText(self, label=f"{step.rate0:.0f} €/h" if step.rate0 > 0 else "—")
            s_rate = wx.Slider(self, value=step.rate_pct, minValue=-100, maxValue=100, size=(110, -1))
            r_sim = wx.StaticText(self, label="", size=(120, -1), style=wx.ST_NO_AUTORESIZE)
            for wdg in (tc0, tc_sim, r0, r_sim):
                wdg.SetForegroundColour(sub_fg)
            if step.tc0_s <= 0 or not op_enabled:
                s_tc.Enable(False)
            if step.rate0 <= 0 or not op_enabled:
                s_rate.Enable(False)
            for wdg in (s_tc, s_rate):
                wdg.Bind(wx.EVT_SLIDER, lambda e, a=i, b=j: self._on_step_slider(a, b))
                wdg.Bind(wx.EVT_SET_FOCUS, lambda e, a=i: (self._select(a), e.Skip()))
            for wdg in (name, tc0, s_tc, tc_sim, r0, s_rate, r_sim):
                self.sizer.Add(wdg, 0, wx.ALIGN_CENTER_VERTICAL
                               | (wx.EXPAND if isinstance(wdg, wx.Slider) else 0))
            for _ in range(6):                                                   # machines … statut
                self.sizer.Add(wx.StaticText(self, label=""), 0)
            self._sub_widgets[(i, j)] = dict(name=name, s_tc=s_tc, tc_sim=tc_sim, s_rate=s_rate, r_sim=r_sim)

    def _toggle(self, i):
        """Déplie / replie les étapes de l'opération i."""
        code = self.rows[i].op.code
        if code in self.expanded:
            self.expanded.discard(code)
        else:
            self.expanded.add(code)
        self._build()
        if callable(self.on_expand):
            self.on_expand(i)

    def _on_step_slider(self, i, j):
        step = self.rows[i].steps[j]
        w = self._sub_widgets[(i, j)]
        step.time_pct = w["s_tc"].GetValue()
        step.rate_pct = w["s_rate"].GetValue()
        if callable(self.on_slider):
            self.on_slider(i)

    def refresh_step_labels(self):
        """Libellés « simulé » des sous-lignes (valeur effective : opération × étape)."""
        for (i, j), w in self._sub_widgets.items():
            step = self.rows[i].steps[j]
            w["tc_sim"].SetLabel(f"{step.tc_sim_s:.2f} s ({step.time_pct:+d} %)" if step.tc0_s > 0 else "—")
            w["r_sim"].SetLabel(f"{step.rate_sim:.0f} €/h ({step.rate_pct:+d} %)" if step.rate0 > 0 else "—")

    def _select(self, i):
        if callable(self.on_select):
            self.on_select(i)

    def _on_slider(self, i):
        row, w = self.rows[i], self._widgets[i]
        row.time_pct = w["s_tc"].GetValue()
        row.rate_pct = w["s_rate"].GetValue()
        if callable(self.on_slider):
            self.on_slider(i)

    def _on_mach(self, i):
        self.rows[i].machines = self._widgets[i]["mach"].GetValue()
        if callable(self.on_machines):
            self.on_machines(i)

    def _on_enable(self, i):
        self.rows[i].enabled = self._widgets[i]["chk"].GetValue()
        if callable(self.on_enable):
            self.on_enable(i)

    def _on_launch(self, i):
        self.rows[i].setup_launch_h = self._widgets[i]["launch"].GetValue()
        if callable(self.on_launch):
            self.on_launch(i)

    def reset(self):
        for row, w in zip(self.rows, self._widgets):
            row.time_pct = row.rate_pct = 0
            w["s_tc"].SetValue(0)
            w["s_rate"].SetValue(0)
            for step in row.steps:
                step.time_pct = step.rate_pct = 0
        for sw in self._sub_widgets.values():
            sw["s_tc"].SetValue(0)
            sw["s_rate"].SetValue(0)

    def get_machine_posts(self):
        """Postes machine reflétant nb de machines et temps de lancement saisis (TC/TH re-dérivés par sync)."""
        return [MachinePost(operation_code=r.op.code, name=r.op.label,
                            machines_available=r.machines,
                            setup_launch_h=getattr(r, "setup_launch_h", 0.0)) for r in self.rows]


# ---------------------------------------------------------------------------
# Helper to build a section header band
# ---------------------------------------------------------------------------

def _section_label(parent, text):
    lbl = wx.StaticText(parent, label=f"  {text}")
    lbl.SetBackgroundColour(SECTION_BG)
    lbl.SetForegroundColour(SECTION_FG)
    font = lbl.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    font.SetPointSize(10)
    lbl.SetFont(font)
    lbl.SetMinSize((-1, 24))
    return lbl


# ---------------------------------------------------------------------------
# Main Panel
# ---------------------------------------------------------------------------

class SeriePricingPanel(wx.Panel):
    """Onglet de chiffrage pour la production grande série."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.on_serie_updated = None  # callback → MainFrame._mark_dirty + save
        self.on_generate_serie_offer = None  # callback → MainFrame._on_export_serie_xlsx
        self.on_preview_serie_offer = None   # callback → MainFrame._on_preview_offer(serie_offer=True)
        self.on_steps_changed = None         # callback → rafraîchir l'éditeur de gamme
        self._building = False        # guard contre les boucles EVT_TEXT
        self._locked = False          # version figée par une offre émise
        self._locked_controls = []    # contrôles désactivés par le verrouillage
        self.on_request_new_version = None   # callback → MainFrame : « Nouvelle version »
        self._eur_usd_rate: float = None
        self._rate_date: str = ""
        self._build_ui()

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        # Bandeau « version figée » (affiché seulement quand une offre a été émise)
        self.lock_banner = wx.Panel(self)
        self.lock_banner.SetBackgroundColour(wx.Colour(255, 247, 230))
        banner_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.lock_text = wx.StaticText(self.lock_banner, label="")
        self.lock_text.SetForegroundColour(wx.Colour(130, 80, 0))
        banner_sizer.Add(self.lock_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 10)
        self.btn_new_version = RibbonButton(self.lock_banner, "➕", "Nouveau scénario",
                                            "Copie de ce scénario, modifiable", accent=TOOLING, size=(250, 50))
        self.btn_new_version.Bind(wx.EVT_BUTTON, lambda e: self.on_request_new_version() if callable(self.on_request_new_version) else None)
        banner_sizer.Add(self.btn_new_version, 0, wx.ALL, 6)
        self.lock_banner.SetSizer(banner_sizer)
        self.lock_banner.Hide()
        outer.Add(self.lock_banner, 0, wx.EXPAND)

        # Top bar: activation toggle + title
        top = wx.BoxSizer(wx.HORIZONTAL)
        self.toggle = wx.ToggleButton(self, label="  Activer le mode Série  ")
        self.toggle.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT,
                                    wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.toggle.Bind(wx.EVT_TOGGLEBUTTON, self._on_toggle)
        top.Add(self.toggle, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)

        self.lbl_status = wx.StaticText(self, label="Mode Série non activé pour ce projet")
        self.lbl_status.SetForegroundColour(wx.Colour(120, 120, 120))
        top.Add(self.lbl_status, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)

        top.AddStretchSpacer(1)

        # Les offres (aperçu, nouvelle offre, indices) se gèrent dans l'onglet « Tarif de Vente ».
        outer.Add(top, 0, wx.EXPAND)

        outer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Dock prix permanent : prix /pièce + décomposition, visible sur tous les onglets.
        self.price_dock = PriceDecompositionBar(self)
        self.price_dock.SetMinSize((-1, 92))
        outer.Add(self.price_dock, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        # Espace de travail unique (sans onglets) :
        #   gauche  = opérations (curseurs + capacité) + goulot  → le cœur permanent
        #   droite  = inspecteur : cadence/programme, coûts partagés, investissements
        self.workspace = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.workspace.SetMinimumPaneSize(300)
        self.workspace.SetSashGravity(0.58)

        self._ops_pane = self._build_operations_pane(self.workspace)

        self.inspector = wx.ScrolledWindow(self.workspace, style=wx.VSCROLL)
        self.inspector.SetScrollRate(0, 20)
        # Chaque section de l'inspecteur est un panneau dépliant (wx.CollapsiblePane)
        # pour organiser l'écran : on replie ce dont on n'a pas besoin.
        self._inspector_sizer = wx.BoxSizer(wx.VERTICAL)
        self._panes = []
        self._build_hypotheses_section()
        self._build_cost_sections()
        self._build_investissements_section()
        self.inspector.SetSizer(self._inspector_sizer)
        self.inspector.FitInside()

        # Inspecteur garanti ~420 px au départ (sash négatif = largeur du volet droit).
        self.workspace.SplitVertically(self._ops_pane, self.inspector, -420)
        outer.Add(self.workspace, 1, wx.EXPAND | wx.ALL, 4)

        # Synthèse de prix / LOP : widgets tenus à jour (dock + onglet « Tarif de Vente »),
        # jamais affichés directement dans ce panneau.
        self._tab_syn = self._build_tab_synthese(self)
        self._tab_syn.Hide()

        self.SetSizer(outer)
        self._set_active(False)

    # ------------------------------------------------------------------ panneaux dépliants

    def _section(self, title, expanded=True):
        """Crée un panneau dépliant dans l'inspecteur ; renvoie (pane, sizer) pour son contenu."""
        cp = wx.CollapsiblePane(self.inspector, label=title,
                                style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
        cp.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_pane_changed)
        self._inspector_sizer.Add(cp, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        self._panes.append(cp)
        if expanded:
            cp.Expand()
        pane = cp.GetPane()
        sz = wx.BoxSizer(wx.VERTICAL)
        pane.SetSizer(sz)
        return pane, sz

    def _on_pane_changed(self, event):
        self.inspector.FitInside()
        self.inspector.Layout()
        event.Skip()

    def _hint(self, parent, text, wrap=330):
        """StaticText d'aide gris, enroulé pour ne pas déborder du panneau info."""
        st = wx.StaticText(parent, label=text)
        st.SetForegroundColour(wx.Colour(100, 100, 100))
        st.Wrap(wrap)
        return st

    # ------------------------------------------------------------------ tab 1 : hypothèses

    def _build_hypotheses_section(self):
        # -- Section production --
        pane, sz = self._section("Production")
        prod_grid = wx.FlexGridSizer(7, 3, 6, 10)
        prod_grid.AddGrowableCol(1, 1)
        self.e_volume        = self._hyp_row(pane, prod_grid, "Volume annuel cible (livraisons)", "100000", "pcs/an")
        self.e_days          = self._hyp_row(pane, prod_grid, "Jours ouvrés / an",                "220",    "j/an")
        self.e_shifts        = self._hyp_row(pane, prod_grid, "Nb équipes / jour",                "2",      "équipes")
        self.e_hshift        = self._hyp_row(pane, prod_grid, "H productives / équipe",           "7.0",    "h")
        self.e_trs           = self._hyp_row(pane, prod_grid, "TRS",                              "0.85",   "(0→1)")
        self.e_scrap_rate    = self._hyp_row(pane, prod_grid, "Taux de rebut interne",            "0.0",    "% (ex: 2.0)")
        self.e_program_years = self._hyp_row(pane, prod_grid, "Durée du programme",               "5",      "ans")
        sz.Add(prod_grid, 0, wx.EXPAND | wx.ALL, 6)

        # -- Rebut calculé (lecture seule) --
        pane, sz = self._section("Impact rebut")
        scrap_grid = wx.FlexGridSizer(2, 2, 4, 10)
        scrap_grid.AddGrowableCol(1, 1)
        self._lbl_prod_vol  = self._result_row(pane, scrap_grid, "Volume production réel / an")
        self._lbl_scrap_vol = self._result_row(pane, scrap_grid, "Rebuts / an")
        sz.Add(scrap_grid, 0, wx.EXPAND | wx.ALL, 6)

        # Les taux horaires ne sont plus saisis ici : ils proviennent des opérations
        # de la gamme (aucun taux de repli). L'overhead éventuel reste porté par les
        # valeurs enregistrées (0 par défaut : TH déjà chargés).

        # -- Computed block --
        pane, sz = self._section("Capacité calculée")
        cap_grid = wx.FlexGridSizer(4, 2, 6, 10)
        cap_grid.AddGrowableCol(1, 1)
        self._lbl_cap_eq  = self._result_row(pane, cap_grid, "Capacité réelle / équipe")
        self._lbl_cap_day = self._result_row(pane, cap_grid, "Capacité réelle / jour")
        self._lbl_cap_yr  = self._result_row(pane, cap_grid, "Capacité réelle / an")
        self._lbl_charge  = self._result_row(pane, cap_grid, "Taux de charge global")
        sz.Add(cap_grid, 0, wx.EXPAND | wx.ALL, 6)

    def _hyp_row(self, parent, fg, label, default, unit):
        fg.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl = wx.TextCtrl(parent, value=default, size=(100, -1))
        ctrl.Bind(wx.EVT_TEXT, self._on_param_changed)
        fg.Add(ctrl, 1, wx.EXPAND)
        fg.Add(wx.StaticText(parent, label=unit), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        return ctrl

    def _result_row(self, parent, fg, label):
        fg.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        lbl = wx.StaticText(parent, label="-")
        lbl.SetBackgroundColour(RESULT_BG)
        font = lbl.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        lbl.SetFont(font)
        fg.Add(lbl, 1, wx.EXPAND | wx.LEFT, 4)
        return lbl

    # ------------------------------------------------------------------ tab 2 : investissements

    def _build_investissements_section(self):
        # CAPEX
        pane, sz = self._section("CAPEX – Investissements machines / équipements")

        mg_sizer = wx.BoxSizer(wx.HORIZONTAL)
        mg_sizer.Add(wx.StaticText(pane, label=" Durée d'amortissement = durée du programme :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._lbl_capex_years = wx.StaticText(pane, label="—")
        self._lbl_capex_years.SetBackgroundColour(RESULT_BG)
        font_cy = self._lbl_capex_years.GetFont()
        font_cy.SetWeight(wx.FONTWEIGHT_BOLD)
        self._lbl_capex_years.SetFont(font_cy)
        mg_sizer.Add(self._lbl_capex_years, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        mg_sizer.Add(wx.StaticText(pane, label=" ans  (réglable dans « Production »)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        sz.Add(mg_sizer, 0, wx.TOP | wx.BOTTOM, 4)

        sz.Add(self._hint(pane,
            "Marge propre à chaque ligne (colonne Marge). Les lignes « Machine » sont liées "
            "aux opérations (désignation et nb de machines pilotés par la liste, non éditables ici)."),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.capex_table = CapexTable(pane, on_change=self._on_table_changed,
                                      serie_ref=self._get_serie_data)
        self.capex_table.SetMinSize((-1, 230))
        sz.Add(self.capex_table, 0, wx.EXPAND | wx.ALL, 6)

        # Tooling (outillages propres à la série ; ceux de la gamme ne sont pas repris)
        pane, sz = self._section("Tooling – Outillages")
        self.tooling_table = ToolingTable(pane, on_change=self._on_table_changed)
        self.tooling_table.SetMinSize((-1, 130))
        sz.Add(self.tooling_table, 0, wx.EXPAND | wx.ALL, 6)

    # ------------------------------------------------------------------ tab 3 : capacité, temps & taux

    def _build_operations_pane(self, parent):
        """Volet gauche (cœur) : barre prix simulé, liste des opérations avec curseurs
        temps/taux + machines + capacité/charge, et graphe goulot en dessous."""
        panel = wx.Panel(parent)
        root = wx.BoxSizer(wx.VERTICAL)

        # -- Barre prix simulé + actions --
        top = wx.BoxSizer(wx.HORIZONTAL)
        self.sens_base = wx.StaticText(panel, label="Prix série actuel : —")
        self.sens_sim = wx.StaticText(panel, label="")
        f = self.sens_sim.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        f.SetPointSize(f.GetPointSize() + 2)
        self.sens_sim.SetFont(f)
        top.Add(self.sens_base, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        top.Add(self.sens_sim, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        top.AddStretchSpacer(1)
        self.btn_sens_reset = wx.Button(panel, label="Réinitialiser")
        self.btn_sens_reset.Bind(wx.EVT_BUTTON, lambda e: self._on_sens_reset())
        self.btn_sens_apply = wx.Button(panel, label="Appliquer à la série")
        self.btn_sens_apply.SetToolTip(
            "Enregistre les temps et taux simulés comme valeurs Série des opérations\n"
            "(appliqués à chaque ligne interne). Le chiffrage Proto n'est pas modifié.")
        self.btn_sens_apply.Bind(wx.EVT_BUTTON, self._on_sens_apply)
        top.Add(self.btn_sens_reset, 0, wx.ALL, 4)
        top.Add(self.btn_sens_apply, 0, wx.ALL, 4)
        root.Add(top, 0, wx.EXPAND)

        hint = wx.StaticText(panel, label=(
            "TC et TH de base sont hérités de la gamme (référence 0 des curseurs). Les curseurs ±100 % "
            "simulent temps/taux sur toutes les lignes internes de l'opération ; capacité et charge suivent "
            "le temps simulé et le nb de machines. Rien n'est enregistré avant « Appliquer »."))
        hint.SetForegroundColour(wx.Colour(100, 100, 100))
        root.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # -- Liste des opérations avec curseurs intégrés --
        self.op_grid = OperationSensGrid(panel, on_slider=self._on_sens_slider,
                                         on_select=self._on_sens_select,
                                         on_machines=self._on_sens_machines,
                                         on_enable=self._on_sens_enabled,
                                         on_launch=self._on_sens_launch,
                                         on_expand=self._on_sens_expand)
        # Min volontairement bas : la grille scrolle horizontalement dans son volet
        # au lieu d'imposer sa pleine largeur (12 colonnes) et d'écraser l'inspecteur.
        self.op_grid.SetMinSize((420, 200))
        root.Add(self.op_grid, 3, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # -- Graphe goulot (capacité vs volume cible) --
        self.sens_chart = CapacityBottleneckChart(panel)
        self.sens_chart.SetMinSize((-1, 200))
        self.sens_chart.on_select = self._on_sens_select
        root.Add(self.sens_chart, 2, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(root)
        return panel

    def _build_cost_sections(self):
        """Panneaux Setup et Achats & Logistique de l'inspecteur."""
        # Setup — indicateurs seulement : le temps de lancement se saisit par opération
        # (colonne « Lancement » de la liste), au taux horaire de l'opération, ventilé
        # sur les pièces produites par équipe. Pas de marge.
        pane, sz = self._section("Setup / Démarrage série")
        sz.Add(self._hint(pane,
            "Temps de lancement défini par opération dans la liste (colonne « Lancement »), "
            "au taux horaire de l'opération, ventilé sur les pièces produites par équipe. "
            "Indicateurs globaux :"),
            0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        setup_grid = wx.FlexGridSizer(4, 2, 6, 10)
        setup_grid.AddGrowableCol(1, 1)
        self._lbl_setup_time   = self._result_row(pane, setup_grid, "Temps de lancement total / équipe")
        self._lbl_pieces_shift = self._result_row(pane, setup_grid, "Pièces produites / équipe (goulot)")
        self._lbl_launch_cost  = self._result_row(pane, setup_grid, "Coût lancement / équipe")
        self._lbl_setup_pc     = self._result_row(pane, setup_grid, "Setup / pièce")
        sz.Add(setup_grid, 0, wx.EXPAND | wx.ALL, 6)

        # Le contrôle de production est désormais saisi comme une opération interne
        # (chiffré ligne à ligne dans la liste des opérations), pas comme un coût séparé ici.

        # Achats
        pane, sz = self._section("Achats")
        sz.Add(self._hint(pane,
            "Achats repris des opérations de sous-traitance / matières de la gamme à la création "
            "(prix au volume série ; « À éditer » = prix indéterminé, à saisir). Éditables (unitaire, "
            "au mètre, ou forfait au lot) ; « + Ajouter » pour un achat propre à la série."),
            0, wx.LEFT | wx.RIGHT | wx.TOP, 6)

        self.purchase_table = PurchaseTable(pane, on_change=self._on_table_changed)
        self.purchase_table.SetMinSize((-1, 150))
        sz.Add(self.purchase_table, 0, wx.EXPAND | wx.ALL, 6)

    # ------------------------------------------------------------------ sensibilité temps/taux (par opération)

    def _sens_factor(self) -> float:
        """€/pc pour 1 s·€/h de (temps par pièce × taux) — MO linéaire."""
        sd = self.project.serie_data
        return (1.0 + sd.overhead_coef) * sd.scrap_factor() * (1.0 + sd.global_commercial_margin) / 3600.0

    def _load_sens(self):
        """(Re)construit la liste des opérations depuis la version courante."""
        if self._phase_serie_data() is None:
            self.op_grid.set_rows([])
            return
        sd = self.project.serie_data
        machines = {p.operation_code: p.machines_available for p in sd.machine_posts}
        launch = {p.operation_code: p.setup_launch_h for p in sd.machine_posts}
        disabled = set(sd.disabled_operation_codes or [])
        rows = []
        for op in self.project.current_version.operations:
            if op.typology in (SUBCONTRACTING_TYPOLOGY, TOOLING_TYPOLOGY):
                continue
            row = _OpSensRow(op)
            row.machines = machines.get(op.code, 1)
            row.setup_launch_h = launch.get(op.code, 0.0)
            row.enabled = op.code not in disabled
            rows.append(row)
        self.op_grid.set_rows(rows)
        self._refresh_capacity_rows()
        self._sens_recompute()

    def _refresh_capacity_rows(self):
        """Capacité / charge / amortissement par opération, en tenant compte du temps simulé.

        La capacité suit le TEMPS SIMULÉ (curseur) et le nb de machines : bouger un
        curseur Temps fait donc varier la charge en direct. Alimente aussi le graphe
        « goulot » en bas à droite.
        """
        if not getattr(self, "op_grid", None) or not self.op_grid.rows:
            if getattr(self, "sens_chart", None):
                self.sens_chart.set_data(None)
            return
        if not self.project or not self.project.serie_data:
            return
        sd = self.project.serie_data
        years = max(sd.program_lifetime_years, 1)
        vol = max(sd.annual_volume, 1)
        capex_by_op = {it.operation_code: it for it in sd.capex_items if it.operation_code}
        items = []
        for idx, (row, w) in enumerate(zip(self.op_grid.rows, self.op_grid._widgets)):
            if not getattr(row, "enabled", True):
                w["cap"].SetLabel("—")
                w["charge"].SetLabel("désactivée")
                w["charge"].SetForegroundColour(wx.Colour(150, 150, 150))
                w["statut"].SetLabel("")
                w["amort"].SetLabel("—")
                continue
            tc = row.tc_sim_s
            cap_eq = cap_an = charge = 0.0
            if tc > 0:
                cap_eq = row.machines * sd.hours_per_shift * 3600.0 / tc * sd.trs
                cap_an = cap_eq * sd.shifts_per_day * sd.working_days_per_year
                # Même base que le taux de charge global : volume produit, rebuts inclus
                charge = (sd.production_volume_per_year() / cap_an) if cap_an > 0 else 0.0
            w["cap"].SetLabel(f"{cap_an:,.0f}".replace(",", " ") if tc > 0 else "—")
            statut = "" if tc <= 0 else ("SURCHARGE" if charge > 0.85 else "OK")
            w["charge"].SetLabel(f"{charge*100:.1f}%" if tc > 0 else "—")
            w["charge"].SetForegroundColour(wx.RED if charge > 0.85 else wx.Colour(0, 140, 0))
            w["statut"].SetLabel(statut)
            w["statut"].SetForegroundColour(wx.Colour(190, 60, 30) if statut == "SURCHARGE"
                                            else wx.Colour(0, 140, 0))
            # Amortissement machine / pièce (coût) depuis la ligne CAPEX liée
            cap_item = capex_by_op.get(row.op.code)
            amort_pc = (cap_item.net_investment / years / vol) if cap_item else 0.0
            w["amort"].SetLabel(f"{amort_pc:.2f} €" if amort_pc > 0 else "—")
            if tc > 0:
                items.append(dict(idx=idx, label=row.label, cap_an=cap_an,
                                  charge=charge, machines=row.machines, tc=tc))
        if getattr(self, "sens_chart", None):
            self.sens_chart.set_data(dict(volume=sd.annual_volume, items=items))

    def _simulated_sd(self) -> SerieData:
        """SerieData reflétant l'état COURANT des curseurs (nominal + simulation).

        Sert à mettre à jour toutes les infos en direct quand on bouge un curseur :
        « Appliquer » ne fait qu'entériner ces valeurs comme nouveau nominal.
        """
        sd = self.project.serie_data
        # Les simulations sont repérées par identité des lignes de coût : on relie chaque
        # ligne de la grille aux opérations ACTUELLES de la version (gamme rechargée/copiée
        # depuis la construction de la grille), sinon le taux global ignorerait le curseur.
        live_ops = {o.code: o for o in self.project.current_version.operations}
        for r in self.op_grid.rows:
            live = live_ops.get(r.op.code)
            if live is not None and live is not r.op:
                r.bind(live)
        overrides = {}
        for r in self.op_grid.rows:
            if r.moved and getattr(r, "enabled", True):
                overrides.update(r.overrides())
        if not overrides:
            return sd
        import copy
        trial = copy.deepcopy(sd)
        trial.sync_from_project(self.project, overrides=overrides)
        return trial

    def _refresh_indicators(self, sd: SerieData):
        """Met à jour tous les indicateurs lus (rebut, capacité, setup, prix, synthèse)
        à partir de `sd` : le nominal courant, ou la variante simulée par les curseurs."""
        prod_vol  = sd.production_volume_per_year()
        scrap_vol = sd.scrap_units_per_year()
        self._lbl_prod_vol .SetLabel(f"{prod_vol:,.0f}  pcs/an")
        self._lbl_scrap_vol.SetLabel(
            f"{scrap_vol:,.0f}  pcs/an" if scrap_vol > 0 else "—  (pas de rebut)")

        cap_eq  = sd.real_capacity_per_shift()
        cap_day = cap_eq * sd.shifts_per_day
        cap_yr  = sd.real_capacity_per_year()
        charge  = sd.load_rate()
        self._lbl_cap_eq .SetLabel(f"{cap_eq:,.0f}  pcs/équipe")
        self._lbl_cap_day.SetLabel(f"{cap_day:,.0f}  pcs/jour")
        self._lbl_cap_yr .SetLabel(f"{cap_yr:,.0f}  pcs/an")
        self._lbl_charge.SetForegroundColour(wx.RED if charge > 0.85 else wx.Colour(0, 140, 0))
        self._lbl_charge.SetLabel(f"{charge*100:.1f} %")

        self._lbl_setup_time  .SetLabel(f"{sd.setup_launch_time_total_h():.2f}  h/équipe")
        self._lbl_pieces_shift.SetLabel(f"{sd.pieces_per_shift():,.0f}  pcs/équipe".replace(",", " "))
        self._lbl_launch_cost .SetLabel(f"{sd.setup_launch_cost_per_shift():,.2f}  €/équipe".replace(",", " "))
        self._lbl_setup_pc    .SetLabel(f"{sd.setup_price_per_piece():.2f}  €/pcs")

        self._refresh_synthese(sd)

    def _sens_recompute(self):
        """Recalcule prix, indicateurs et synthèse à partir de l'état COURANT des curseurs."""
        if not getattr(self, "op_grid", None):
            return
        if self._phase_serie_data() is None:
            self.sens_base.SetLabel("Le chiffrage Décomposé porte sur un scénario Série.")
            self.sens_sim.SetLabel("")
            self.sens_chart.set_data(None)
            self.btn_sens_apply.Enable(False)
            self.btn_sens_reset.Enable(False)
            return
        sd = self.project.serie_data
        rows = self.op_grid.rows
        trial = self._simulated_sd()
        p_base = sd.selling_price_per_piece()
        p_sim = trial.selling_price_per_piece()
        delta = p_sim - p_base
        any_moved = any(r.moved for r in rows)
        self.sens_base.SetLabel(f"Prix série actuel : {_eur(p_base, 2)}/pc")
        if any_moved:
            pct = (delta / p_base * 100) if p_base else 0
            self.sens_sim.SetLabel(f"→ simulé : {_eur(p_sim, 2)}/pc  ({delta:+.2f} € · {pct:+.1f} %)")
            self.sens_sim.SetForegroundColour(wx.Colour(30, 130, 50) if delta < 0 else wx.Colour(190, 60, 30))
        else:
            self.sens_sim.SetLabel("")
        self.btn_sens_apply.Enable(any_moved and not self._locked)
        self.btn_sens_reset.Enable(any_moved and not self._locked)

        # Labels simulés par opération + mise en évidence de la sélection
        for idx, (row, w) in enumerate(zip(rows, self.op_grid._widgets)):
            # Variation réelle de l'opération : curseurs de l'opération ET réglages d'étapes
            t_pct = (row.tc_sim_s / row.tc0_s - 1) * 100 if row.tc0_s > 0 else 0.0
            r_pct = (row.rate_sim / row.rate0 - 1) * 100 if row.rate0 > 0 else 0.0
            w["tc_sim"].SetLabel(f"{row.tc_sim_s:.2f} s ({t_pct:+.0f} %)" if row.tc0_s > 0 else "—")
            w["r_sim"].SetLabel(f"{row.rate_sim:.0f} €/h ({r_pct:+.0f} %)" if row.rate0 > 0 else "—")
            sel = idx == self.op_grid.selected
            w["name"].SetLabel(("▶ " if sel else "  ") + row.label)
            if not getattr(row, "enabled", True):
                w["name"].SetForegroundColour(wx.Colour(150, 150, 150))
            else:
                w["name"].SetForegroundColour(wx.Colour(30, 90, 160) if sel else wx.BLACK)
            w["name"].Refresh()
        self.op_grid.refresh_step_labels()   # sous-lignes des opérations dépliées

        # Toutes les infos (prix, dock, synthèse, setup, capacité) suivent l'état simulé.
        self._refresh_indicators(trial)

        # Le graphe « goulot » (bas-droite) est alimenté par _refresh_capacity_rows().
        self.op_grid.Layout()

    def _on_sens_slider(self, idx):
        self.op_grid.selected = idx
        self._refresh_capacity_rows()   # charge + goulot suivent le temps simulé
        self._sens_recompute()

    def _on_sens_expand(self, idx):
        """Opération dépliée / repliée : la grille a été reconstruite, on réaffiche capacités et libellés."""
        self._refresh_capacity_rows()
        self._sens_recompute()

    def _on_sens_select(self, idx):
        if idx != self.op_grid.selected:
            self.op_grid.selected = idx
            self._sens_recompute()

    def _on_sens_machines(self, idx):
        sd = self.project.serie_data if self.project else None
        if sd is None:
            return
        sd.machine_posts = self.op_grid.get_machine_posts()
        sd.sync_from_project(self.project)
        self._refresh_computed()
        self._notify()

    def _on_sens_launch(self, idx):
        """Temps de lancement d'une opération modifié : recalcul du setup."""
        sd = self.project.serie_data if self.project else None
        if sd is None:
            return
        sd.machine_posts = self.op_grid.get_machine_posts()
        sd.sync_from_project(self.project)
        self._refresh_computed()
        self._notify()

    def _on_sens_enabled(self, idx):
        """Case Actif cochée/décochée : exclut l'opération du calcul série."""
        sd = self.project.serie_data if self.project else None
        if sd is None:
            return
        sd.disabled_operation_codes = [r.op.code for r in self.op_grid.rows if not r.enabled]
        sd.machine_posts = self.op_grid.get_machine_posts()
        sd.sync_from_project(self.project)
        self._load_sens()        # reconstruit la grille : grise les lignes désactivées
        self._refresh_computed()
        self._notify()

    def _on_sens_reset(self):
        self.op_grid.reset()
        self._sens_recompute()

    def _on_sens_apply(self, event):
        moved = [r for r in self.op_grid.rows if r.moved]
        if not moved:
            return
        for r in moved:
            r.apply()
        self._on_sensitivity_applied()
        self._load_sens()

    # ------------------------------------------------------------------ tab 4 : synthèse

    def _build_tab_synthese(self, parent):
        panel = wx.ScrolledWindow(parent, style=wx.VSCROLL)
        panel.SetScrollRate(0, 20)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(_section_label(panel, "Synthèse coût de revient & prix de vente"), 0, wx.EXPAND | wx.TOP, 6)

        mg_sizer = wx.BoxSizer(wx.HORIZONTAL)
        mg_sizer.Add(wx.StaticText(panel, label=" Marge commerciale globale MW (%) :"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self.e_global_margin = wx.SpinCtrlDouble(panel, min=0, max=100, initial=25, inc=1, size=(80, -1))
        self.e_global_margin.Bind(wx.EVT_SPINCTRLDOUBLE, self._on_param_changed)
        mg_sizer.Add(self.e_global_margin, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        sizer.Add(mg_sizer, 0, wx.TOP | wx.BOTTOM, 4)

        self.syn_grid = gridlib.Grid(panel)
        self.syn_grid.CreateGrid(0, 4)
        self.syn_grid.SetColLabelValue(0, "Poste de coût")
        self.syn_grid.SetColLabelValue(1, "Coût brut €/pcs")
        self.syn_grid.SetColLabelValue(2, "Marge / Prix client €/pcs")
        self.syn_grid.SetColLabelValue(3, "% du total")
        self.syn_grid.SetColSize(0, 220)
        self.syn_grid.SetColSize(1, 140)
        self.syn_grid.SetColSize(2, 180)
        self.syn_grid.SetColSize(3, 100)
        self.syn_grid.EnableEditing(False)
        self.syn_grid.SetRowLabelSize(0)
        sizer.Add(self.syn_grid, 2, wx.EXPAND | wx.ALL, 6)

        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        price_box = wx.BoxSizer(wx.HORIZONTAL)

        pv_label = wx.StaticText(panel, label="PRIX DE VENTE / PIÈCE :")
        pv_label.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        price_box.Add(pv_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)

        self.lbl_pv = wx.StaticText(panel, label="—")
        self.lbl_pv.SetFont(wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.lbl_pv.SetForegroundColour(wx.Colour(30, 90, 160))
        price_box.Add(self.lbl_pv, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)

        sep = wx.StaticText(panel, label="  ≈")
        sep.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sep.SetForegroundColour(wx.Colour(140, 140, 140))
        price_box.Add(sep, 0, wx.ALIGN_CENTER_VERTICAL)

        self.lbl_pv_usd = wx.StaticText(panel, label="— USD")
        self.lbl_pv_usd.SetFont(wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.lbl_pv_usd.SetForegroundColour(wx.Colour(180, 90, 0))
        price_box.Add(self.lbl_pv_usd, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)

        price_box.AddStretchSpacer()

        ca_label = wx.StaticText(panel, label="CA annuel :")
        ca_label.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        price_box.Add(ca_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)

        self.lbl_ca = wx.StaticText(panel, label="—")
        self.lbl_ca.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.lbl_ca.SetForegroundColour(wx.Colour(50, 140, 50))
        price_box.Add(self.lbl_ca, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)

        sizer.Add(price_box, 0, wx.EXPAND)

        # Barre taux de change
        rate_bar = wx.BoxSizer(wx.HORIZONTAL)
        self._lbl_rate = wx.StaticText(panel, label="EUR/USD : —  (non chargé)")
        self._lbl_rate.SetForegroundColour(wx.Colour(110, 110, 110))
        f_rate = self._lbl_rate.GetFont()
        f_rate.SetPointSize(8)
        self._lbl_rate.SetFont(f_rate)
        rate_bar.Add(self._lbl_rate, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        self._btn_rate = wx.Button(panel, label="↻", size=(28, 22))
        self._btn_rate.SetToolTip("Actualiser le taux EUR/USD (données BCE via Frankfurter)")
        self._btn_rate.Bind(wx.EVT_BUTTON, lambda e: self._fetch_eur_usd_rate())
        rate_bar.Add(self._btn_rate, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        sizer.Add(rate_bar, 0, wx.BOTTOM, 6)

        # Life of Program block
        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        sizer.Add(_section_label(panel, "Life of Program (LOP)"), 0, wx.EXPAND | wx.TOP, 4)
        lop_grid = wx.FlexGridSizer(7, 2, 6, 10)
        lop_grid.AddGrowableCol(1, 1)
        self._lbl_lop_years    = self._result_row(panel, lop_grid, "Durée programme")
        self._lbl_lop_vol      = self._result_row(panel, lop_grid, "Volume total livré")
        self._lbl_lop_revenue  = self._result_row(panel, lop_grid, "CA total programme")
        self._lbl_lop_cost     = self._result_row(panel, lop_grid, "Coût total programme")
        self._lbl_lop_capex    = self._result_row(panel, lop_grid, "  ↳ dont CAPEX net (fixe)")
        self._lbl_lop_tooling  = self._result_row(panel, lop_grid, "  ↳ dont Tooling (fixe)")
        self._lbl_lop_variable = self._result_row(panel, lop_grid, "  ↳ dont MO + setup + ctrl + mat. (variable)")
        sizer.Add(lop_grid, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        return panel

    # ------------------------------------------------------------------ load / refresh

    def _phase_serie_data(self):
        """Données série de la phase active si elle est de type Série (créées au besoin)."""
        if not self.project or not self.project.current_phase.is_serie:
            return None
        phase = self.project.current_phase
        if phase.serie_data is None:
            phase.serie_data = SerieData.new_for_phase()
        return phase.serie_data

    def load_project(self, project: Project):
        self.project = project
        self._building = True
        try:
            active = self._phase_serie_data() is not None
            self._set_active(active)
            if active:
                # Synchronise les postes machine depuis les opérations du projet
                project.serie_data.sync_from_project(project)
                self._load_fields(project.serie_data)
                self._load_sens()
                self._refresh_computed()
                if self._eur_usd_rate is None:
                    self._fetch_eur_usd_rate()
        finally:
            self._building = False

    def refresh_data(self):
        """Appelé depuis MainFrame quand les opérations du projet changent."""
        if self._phase_serie_data() is None:
            return
        self._building = True
        try:
            self.project.serie_data.sync_from_project(self.project)
            self._load_sens()
            self._refresh_computed()
        finally:
            self._building = False

    def _load_fields(self, sd: SerieData):
        self.e_volume.ChangeValue(str(sd.annual_volume))
        self.e_days.ChangeValue(str(sd.working_days_per_year))
        self.e_shifts.ChangeValue(str(sd.shifts_per_day))
        self.e_hshift.ChangeValue(str(sd.hours_per_shift))
        self.e_trs.ChangeValue(str(sd.trs))
        self.e_scrap_rate.ChangeValue(str(sd.scrap_rate * 100))
        self.e_program_years.ChangeValue(str(sd.program_lifetime_years))

        self._lbl_capex_years.SetLabel(str(sd.program_lifetime_years))
        self.capex_table.set_items(sd.capex_items)
        self.tooling_table.set_items(sd.tooling_items)
        self.purchase_table.set_items(sd.purchase_items)
        # Nb de machines et temps de lancement par opération : chargés dans la grille via _load_sens().

        self.e_global_margin.SetValue(sd.global_commercial_margin * 100)

    def _collect_serie_data(self) -> SerieData:
        """Lit les champs UI et construit un SerieData à jour.

        TC/TH des postes machines ne sont PAS collectés depuis l'UI :
        ils restent tels que synchronisés depuis les opérations du projet.
        """
        def f(ctrl, default=0.0):
            try:
                return float(ctrl.GetValue().replace(",", ".").replace(" ", ""))
            except Exception:
                return default

        def i(ctrl, default=1):
            try:
                return int(float(ctrl.GetValue().replace(",", ".").replace(" ", "")))
            except Exception:
                return default

        # Récupère les postes avec machines_available mis à jour depuis la grille d'opérations
        machine_posts = self.op_grid.get_machine_posts()

        # Partir des données existantes : les champs non affichés (synchronisation,
        # outillages repris, surcharges…) sont conservés.
        current = self.project.serie_data if self.project and self.project.serie_data else SerieData()
        sd = dataclasses.replace(
            current,
            sync_purchases=current.sync_purchases,
            sync_tooling=current.sync_tooling,
            setup_from_fixed_times=current.setup_from_fixed_times,
            annual_volume=i(self.e_volume, 100000),
            working_days_per_year=i(self.e_days, 220),
            shifts_per_day=i(self.e_shifts, 2),
            hours_per_shift=f(self.e_hshift, 7.0),
            trs=f(self.e_trs, 0.85),
            scrap_rate=min(f(self.e_scrap_rate, 0.0) / 100.0, 0.99),
            program_lifetime_years=max(1, i(self.e_program_years, 5)),
            fallback_cycle_time_s=current.fallback_cycle_time_s,
            # Taux horaires et overhead : plus de saisie ici, tout vient des opérations.
            mo_production_rate=current.mo_production_rate,
            mo_quality_rate=current.mo_quality_rate,
            overhead_coef=current.overhead_coef,
            capex_items=self.capex_table.get_items(),
            capex_global_margin=current.capex_global_margin,
            tooling_items=self.tooling_table.get_items(),
            machine_posts=machine_posts,
            # Setup : temps de lancement porté par opération (machine_posts) ; pas de marge.
            setup_launch_time_h=current.setup_launch_time_h,
            tooling_setup_time_h=current.tooling_setup_time_h,
            sop_validation_time_h=current.sop_validation_time_h,
            lot_size=current.lot_size,
            setup_margin=current.setup_margin,
            # Contrôle = opération de gamme : plus de coût contrôle séparé (freq 0 → 0 €/pc).
            spc_frequency=0,
            spc_time_per_piece_min=current.spc_time_per_piece_min,
            control_100pct_time_s=current.control_100pct_time_s,
            control_mode="SPC",
            material_cost_per_piece=current.material_cost_per_piece,
            material_margin=current.material_margin,
            # Logistique retirée de l'UI : conservée (0 par défaut) pour compat fichiers.
            logistics_cost_per_piece=current.logistics_cost_per_piece,
            logistics_margin=current.logistics_margin,
            purchase_items=self.purchase_table.get_items(),
            global_commercial_margin=self.e_global_margin.GetValue() / 100.0,
        )
        return sd

    def _refresh_computed(self):
        """Met à jour les labels de résultats et la grille de synthèse."""
        if not self.project or not self.project.serie_data:
            return
        sd = self.project.serie_data
        # Contrôle = opération de gamme : neutralise tout coût contrôle séparé hérité
        # d'anciens fichiers, pour que le prix affiché soit cohérent dès le chargement.
        sd.spc_frequency = 0
        # Outillage NON repris de la gamme : les outillages amortis de la gamme sont
        # ignorés à 100 % en série, y compris sur d'anciens fichiers (sync_tooling=True).
        sd.sync_tooling = False

        self.inspector.Layout()

        # -- Reprise des machines dans les lignes CAPEX (amortissement) --
        self._sync_machine_capex(sd)
        self.capex_table.set_items(sd.capex_items)
        self.purchase_table.set_items(sd.purchase_items)
        self._lbl_capex_years.SetLabel(str(sd.program_lifetime_years))
        self.inspector.FitInside()   # tables redimensionnées → recalcule la zone scrollable

        # Indicateurs + synthèse : _sens_recompute() les met à jour à partir de l'état
        # simulé (nominal si aucun curseur n'a bougé), pour que tout suive en direct.
        self._refresh_capacity_rows()
        self._sens_recompute()

    def _sync_machine_capex(self, sd: SerieData):
        """Assure une ligne CAPEX « Machine » par opération équipée (amortissement).

        Les montants saisis (coût, résiduel, marge) sont conservés par operation_code ;
        la désignation et le nb de machines suivent le poste de la liste des opérations.
        Les lignes CAPEX manuelles (operation_code == "") restent intactes, à la suite.
        """
        by_op = {it.operation_code: it for it in sd.capex_items if it.operation_code}
        manual = [it for it in sd.capex_items if not it.operation_code]
        machine_rows = []
        seen = set()
        for p in sd.machine_posts:
            if not p.operation_code or p.cycle_time_s <= 0 or p.operation_code in seen:
                continue   # une seule ligne CAPEX machine par code opération
            seen.add(p.operation_code)
            it = by_op.get(p.operation_code)
            if it is None:
                it = CapexItem(operation_code=p.operation_code, margin_rate=sd.capex_global_margin)
            it.name = f"Machine · {p.name}"
            it.machines_count = max(p.machines_available, 1)
            machine_rows.append(it)
        sd.capex_items = machine_rows + manual

    def _refresh_synthese(self, sd: SerieData):
        grid = self.syn_grid
        grid.BeginBatch()
        if grid.GetNumberRows() > 0:
            grid.DeleteRows(0, grid.GetNumberRows())

        rows = [
            ("MO directe production",
             sd.mo_cost_per_piece(),
             sd.mo_cost_per_piece()),
            ("CAPEX – amortissement",
             sd.capex_cost_per_piece(),
             sd.capex_price_per_piece()),
            ("Tooling / Outillages",
             sd.tooling_cost_per_piece(),
             sd.tooling_price_per_piece()),
            ("Setup / Démarrage",
             sd.setup_cost_per_piece(),
             sd.setup_price_per_piece()),
            ("Contrôle qualité",
             sd.control_cost_per_piece(),
             sd.control_cost_per_piece()),
            ("Matières premières / achats",
             sd.purchase_cost_per_piece(),
             sd.purchase_price_per_piece()),
            ("Logistique / Emballage",
             sd.logistics_cost_per_piece,
             sd.logistics_cost_per_piece * (1 + sd.logistics_margin)),
        ]

        subtotal_price = sd.subtotal_with_item_margins()
        total_cost     = sd.total_cost_per_piece()
        pv             = sd.selling_price_per_piece()

        grid.AppendRows(len(rows) + 2)

        for r, (label, cost, price) in enumerate(rows):
            pct = (price / pv * 100) if pv > 0 else 0
            grid.SetCellValue(r, 0, label)
            grid.SetCellValue(r, 1, f"{cost:.2f} €")
            grid.SetCellValue(r, 2, f"{price:.2f} €")
            grid.SetCellValue(r, 3, f"{pct:.1f} %")
            grid.SetCellAlignment(r, 1, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            grid.SetCellAlignment(r, 2, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            grid.SetCellAlignment(r, 3, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)

        r_sub = len(rows)
        grid.SetCellValue(r_sub, 0, "SOUS-TOTAL (avant marge commerciale)")
        grid.SetCellValue(r_sub, 1, f"{total_cost:.2f} €")
        grid.SetCellValue(r_sub, 2, f"{subtotal_price:.2f} €")
        grid.SetCellValue(r_sub, 3, "—")
        for c in range(4):
            grid.SetCellBackgroundColour(r_sub, c, TOTAL_BG)
            grid.SetCellFont(r_sub, c,
                             wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        r_tot = len(rows) + 1
        grid.SetCellValue(r_tot, 0, f"PRIX DE VENTE (marge ciale {sd.global_commercial_margin*100:.0f}%)")
        grid.SetCellValue(r_tot, 1, "")
        grid.SetCellValue(r_tot, 2, f"{pv:.2f} €")
        grid.SetCellValue(r_tot, 3, "100 %")
        for c in range(4):
            grid.SetCellBackgroundColour(r_tot, c, wx.Colour(30, 90, 160))
            grid.SetCellTextColour(r_tot, c, wx.WHITE)
            grid.SetCellFont(r_tot, c,
                             wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        grid.AutoSizeColumns()
        grid.EndBatch()

        self.lbl_pv.SetLabel(f"{pv:.2f} €")
        self.lbl_ca.SetLabel(f"{sd.annual_revenue():,.0f} €/an")

        # Dock prix permanent : décomposition par poste (prix /pièce)
        segments = [dict(label=COST_COLOURS[i][0], value=max(price, 0.0), colour=COST_COLOURS[i][1])
                    for i, (_, _, price) in enumerate(rows)]
        mlabel, mcolour = COST_COLOURS[-1]
        segments.append(dict(label=mlabel, value=max(pv - subtotal_price, 0.0), colour=mcolour))
        self.price_dock.set_data(dict(
            price=pv,
            price_usd=(pv * self._eur_usd_rate if self._eur_usd_rate else None),
            total_cost=total_cost,
            segments=segments,
        ))

        # LOP
        capex_fixed    = sd.total_capex_net_investment()
        tooling_fixed  = sd.total_tooling_investment()
        variable_cost  = sd.total_variable_program_cost()
        self._lbl_lop_years   .SetLabel(f"{sd.program_lifetime_years} ans")
        self._lbl_lop_vol     .SetLabel(f"{sd.total_program_volume():,}  pcs")
        self._lbl_lop_revenue .SetLabel(f"{sd.total_program_revenue():,.0f}  €")
        self._lbl_lop_cost    .SetLabel(f"{sd.total_program_cost():,.0f}  €")
        self._lbl_lop_capex   .SetLabel(
            f"{capex_fixed:,.0f}  €  (constant)" if capex_fixed > 0 else "—")
        self._lbl_lop_tooling .SetLabel(
            f"{tooling_fixed:,.0f}  €  (constant)" if tooling_fixed > 0 else "—")
        self._lbl_lop_variable.SetLabel(f"{variable_cost:,.0f}  €  (∝ volume)")

        self._refresh_usd_price()
        self._tab_syn.Layout()

    # ------------------------------------------------------------------ events

    def _on_toggle(self, event):
        active = self.toggle.GetValue()
        if active and self.project:
            if self.project.serie_data is None:
                self.project.serie_data = SerieData()
            # Sync posts from operations before loading fields
            self.project.serie_data.sync_from_project(self.project)
            self._load_fields(self.project.serie_data)
            self._load_sens()
            self._refresh_computed()
            if self._eur_usd_rate is None:
                self._fetch_eur_usd_rate()
        elif not active and self.project:
            self.project.serie_data = None
        self._set_active(active)
        self._notify()

    def _on_param_changed(self, event):
        if self._building or self._locked:
            event.Skip()
            return
        self._commit_to_model()
        event.Skip()

    def _on_table_changed(self):
        self._commit_to_model()

    def _commit_to_model(self):
        if self._locked or not self.project or not self.project.serie_data:
            return
        new_sd = self._collect_serie_data()
        self.project.serie_data = new_sd
        # Reprise depuis la gamme (cases de synchronisation, volume annuel…)
        new_sd.sync_from_project(self.project)
        self._refresh_computed()
        self._notify()

    def _on_sensitivity_applied(self):
        """Valeurs TC / taux simulées enregistrées sur les étapes : recalcul série."""
        self.project.serie_data.sync_from_project(self.project)
        self._refresh_computed()
        self._notify()
        if callable(self.on_steps_changed):
            self.on_steps_changed()

    def _notify(self):
        if self.on_serie_updated:
            self.on_serie_updated()

    # ------------------------------------------------------------------ helpers

    def _set_active(self, active: bool):
        # L'activation suit la phase : une phase Série = un chiffrage série
        self.toggle.SetValue(active)
        self.toggle.Hide()
        if active:
            self.lbl_status.SetLabel(f"Scénario « {self.project.current_phase.display_label} » — chiffrage Décomposé")
            self.lbl_status.SetForegroundColour(wx.Colour(30, 120, 30))
        else:
            self.lbl_status.SetLabel(
                "Ce scénario est chiffré au taux horaire (onglet Tarif de vente).\n"
                "Pour la chiffrer en Décomposé, créez un nouveau scénario de type Décomposé "
                "(« + Nouveau scénario »).")
            self.lbl_status.SetForegroundColour(wx.Colour(120, 120, 120))
        self.workspace.Show(active)
        self.price_dock.Show(active)
        self.Layout()
        if active:
            wx.CallAfter(self._place_sash)

    def _place_sash(self):
        """Fixe la largeur de l'inspecteur une fois le volet réellement dimensionné."""
        if not getattr(self, "workspace", None) or not self.workspace.IsShownOnScreen():
            return
        w = self.workspace.GetClientSize().width
        if w > 760:
            self.workspace.SetSashPosition(w - 440)

    # ------------------------------------------------------------------ verrouillage

    @property
    def is_locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool, frozen_by: str = "") -> None:
        """Scénario Décomposé figé (offre émise) : lecture seule, bandeau « Nouveau scénario »."""
        locked = bool(locked)
        if locked:
            who = f" (offre {frozen_by})" if frozen_by else ""
            self.lock_text.SetLabel(f"🔒  Scénario émis{who} : le chiffrage Décomposé est figé. "
                                    "Pour le modifier, créez un nouveau scénario.")
        if locked != self._locked or locked:
            for ctrl in self._locked_controls:
                try:
                    ctrl.Enable(True)
                except RuntimeError:
                    pass
            self._locked_controls = []
            self._locked = locked
            if locked:
                self._disable_inputs(self.workspace)
            elif self.project and self.project.serie_data:
                self._refresh_computed()          # rétablit les champs désactivés par la synchro
        self.lock_banner.Show(locked)
        self.Layout()

    def _disable_inputs(self, window):
        inputs = (wx.TextCtrl, wx.Choice, wx.CheckBox, wx.Button, wx.ComboBox, wx.SpinCtrl, wx.SpinCtrlDouble)
        for child in window.GetChildren():
            if isinstance(child, inputs) and child.IsEnabled():
                child.Enable(False)
                self._locked_controls.append(child)
            self._disable_inputs(child)

    def _on_generate_serie_offer(self, event):
        if callable(self.on_generate_serie_offer):
            self.on_generate_serie_offer()

    def _on_preview_serie_offer(self, event):
        if callable(self.on_preview_serie_offer):
            self.on_preview_serie_offer()

    # ------------------------------------------------------------------ EUR/USD

    def _fetch_eur_usd_rate(self):
        """Charge le taux EUR/USD partagé (voir infrastructure/fx_rate.py)."""
        from infrastructure.fx_rate import FxRate
        self._lbl_rate.SetLabel("EUR/USD : chargement…")
        self._btn_rate.Disable()

        def _done(ok, message):
            try:
                self._eur_usd_rate = FxRate.rate
                self._lbl_rate.SetLabel(message)
                self._btn_rate.Enable()
                self._refresh_usd_price()
            except RuntimeError:
                pass
        FxRate.fetch_async(_done)

    def _refresh_usd_price(self):
        if not self.project or not self.project.serie_data:
            self.lbl_pv_usd.SetLabel("— USD")
            return
        pv = self.project.serie_data.selling_price_per_piece()
        if self._eur_usd_rate and pv > 0:
            self.lbl_pv_usd.SetLabel(f"{pv * self._eur_usd_rate:.2f} USD")
        else:
            self.lbl_pv_usd.SetLabel("— USD")

    def _get_annual_volume(self) -> int:
        try:
            return int(float(self.e_volume.GetValue().replace(",", "").replace(" ", "")))
        except Exception:
            return 1

    def _get_serie_data(self):
        if self.project:
            return self.project.serie_data
        return None
