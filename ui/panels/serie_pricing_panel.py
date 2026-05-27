# ui/panels/serie_pricing_panel.py
import wx
import wx.grid as gridlib
from domain.project import Project
from domain.serie_data import SerieData, CapexItem, ToolingItem, MachinePost


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
        super().__init__(parent, title="CAPEX – Équipement", size=(420, 240))
        item = item or CapexItem()
        sizer = wx.BoxSizer(wx.VERTICAL)
        fg = wx.FlexGridSizer(4, 2, 8, 12)
        fg.AddGrowableCol(1, 1)

        self.name   = self._row(fg, "Désignation",           wx.TextCtrl(self, value=item.name))
        self.cost   = self._row(fg, "Coût d'achat (€)",      wx.TextCtrl(self, value=str(item.cost)))
        self.resid  = self._row(fg, "Valeur résiduelle (€)",  wx.TextCtrl(self, value=str(item.residual_value)))
        self.margin = self._row(fg, "Marge MW (%)",           wx.SpinCtrlDouble(self, min=0, max=100,
                                                                                initial=item.margin_rate * 100, inc=1))

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
    COLS = [("Désignation", 180), ("Coût €", 90), ("Résiduel €", 80),
            ("Marge", 60), ("Amort/an €", 90), ("Prix/pc €", 110)]

    def __init__(self, parent, on_change=None, serie_ref=None):
        super().__init__(parent, self.COLS, on_change)
        self.set_dialog_class(CapexDialog)
        self._serie_ref = serie_ref  # callable → SerieData (pour volume et durée amort.)

    def _append_row(self, item: CapexItem):
        sd = self._serie_ref() if self._serie_ref else None
        years = sd.program_lifetime_years if sd and sd.program_lifetime_years > 0 else 1
        vol   = sd.annual_volume if sd and sd.annual_volume > 0 else 1
        amort_an = (item.cost - item.residual_value) / years
        cost_pc  = amort_an / vol
        price_pc = cost_pc * (1 + item.margin_rate)
        idx = self.lc.InsertItem(self.lc.GetItemCount(), item.name)
        self.lc.SetItem(idx, 1, f"{item.cost:,.0f}")
        self.lc.SetItem(idx, 2, f"{item.residual_value:,.0f}")
        self.lc.SetItem(idx, 3, f"{item.margin_rate*100:.0f}%")
        self.lc.SetItem(idx, 4, f"{amort_an:,.0f}")
        self.lc.SetItem(idx, 5, f"{price_pc:.4f}")


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
        self.lc.SetItem(idx, 4, f"{cost_pc:.4f}")
        self.lc.SetItem(idx, 5, f"{price_pc:.4f}")


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
        self._building = False        # guard contre les boucles EVT_TEXT
        self._eur_usd_rate: float = None
        self._rate_date: str = ""
        self._build_ui()

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

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
        outer.Add(top, 0, wx.EXPAND)

        outer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Sub-notebook (only visible when active)
        self.nb = wx.Notebook(self)
        self._tab_hyp   = self._build_tab_hypotheses(self.nb)
        self._tab_inv   = self._build_tab_investissements(self.nb)
        self._tab_cap   = self._build_tab_capacite(self.nb)
        self._tab_syn   = self._build_tab_synthese(self.nb)
        self.nb.AddPage(self._tab_hyp, "Hypothèses")
        self.nb.AddPage(self._tab_inv, "CAPEX & Tooling")
        self.nb.AddPage(self._tab_cap, "Capacité & Coûts")
        self.nb.AddPage(self._tab_syn, "Synthèse")
        outer.Add(self.nb, 1, wx.EXPAND | wx.ALL, 4)

        self.SetSizer(outer)
        self._set_active(False)

    # ------------------------------------------------------------------ tab 1 : hypothèses

    def _build_tab_hypotheses(self, parent):
        panel = wx.ScrolledWindow(parent, style=wx.VSCROLL)
        panel.SetScrollRate(0, 20)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # -- Section production --
        sizer.Add(_section_label(panel, "Production"), 0, wx.EXPAND | wx.TOP, 6)
        prod_grid = wx.FlexGridSizer(7, 3, 6, 10)
        prod_grid.AddGrowableCol(1, 1)

        self.e_volume        = self._hyp_row(panel, prod_grid, "Volume annuel cible (livraisons)", "100000", "pcs/an")
        self.e_days          = self._hyp_row(panel, prod_grid, "Jours ouvrés / an",                "220",    "j/an")
        self.e_shifts        = self._hyp_row(panel, prod_grid, "Nb équipes / jour",                "2",      "équipes")
        self.e_hshift        = self._hyp_row(panel, prod_grid, "H productives / équipe",           "7.0",    "h")
        self.e_trs           = self._hyp_row(panel, prod_grid, "TRS",                              "0.85",   "(0→1)")
        self.e_scrap_rate    = self._hyp_row(panel, prod_grid, "Taux de rebut interne",            "0.0",    "% (ex: 2.0)")
        self.e_program_years = self._hyp_row(panel, prod_grid, "Durée du programme",               "5",      "ans")
        sizer.Add(prod_grid, 0, wx.EXPAND | wx.ALL, 8)

        # -- Rebut calculé (lecture seule) --
        sizer.Add(_section_label(panel, "Impact rebut"), 0, wx.EXPAND | wx.TOP, 4)
        scrap_grid = wx.FlexGridSizer(2, 2, 4, 10)
        scrap_grid.AddGrowableCol(1, 1)
        self._lbl_prod_vol  = self._result_row(panel, scrap_grid, "Volume production réel / an")
        self._lbl_scrap_vol = self._result_row(panel, scrap_grid, "Rebuts / an")
        sizer.Add(scrap_grid, 0, wx.EXPAND | wx.ALL, 8)

        # -- TC goulot calculé (lecture seule) --
        sizer.Add(_section_label(panel, "Temps de cycle goulot (calculé depuis les Opérations)"), 0, wx.EXPAND | wx.TOP, 8)
        tc_grid = wx.FlexGridSizer(2, 3, 6, 10)
        tc_grid.AddGrowableCol(1, 1)

        # Fallback TC : utilisé uniquement si aucune opération interne n'existe dans le projet
        self.e_fallback_tc = self._hyp_row(panel, tc_grid, "TC de secours (sans op. interne)", "0.0", "s/pcs")

        tc_grid.Add(wx.StaticText(panel, label="TC goulot effectif"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._lbl_goulot = wx.StaticText(panel, label="—")
        self._lbl_goulot.SetBackgroundColour(RESULT_BG)
        font = self._lbl_goulot.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self._lbl_goulot.SetFont(font)
        tc_grid.Add(self._lbl_goulot, 1, wx.EXPAND | wx.LEFT, 4)
        tc_grid.Add(wx.StaticText(panel, label="s/pcs  (= max TC_poste / nb_machines)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        sizer.Add(tc_grid, 0, wx.EXPAND | wx.ALL, 8)

        # -- Section coûts horaires --
        sizer.Add(_section_label(panel, "Taux horaires"), 0, wx.EXPAND | wx.TOP, 8)
        rate_grid = wx.FlexGridSizer(3, 3, 6, 10)
        rate_grid.AddGrowableCol(1, 1)
        self.e_mo_prod  = self._hyp_row(panel, rate_grid, "MO Production (setup, fallback)", "28.0", "€/h")
        self.e_mo_qual  = self._hyp_row(panel, rate_grid, "MO Qualité",                      "28.0", "€/h")
        self.e_overhead = self._hyp_row(panel, rate_grid, "Coef. structure overhead",        "0.0",  "(0 si TH déjà chargé)")
        sizer.Add(rate_grid, 0, wx.EXPAND | wx.ALL, 8)

        # -- Computed block --
        sizer.Add(_section_label(panel, "Capacité calculée"), 0, wx.EXPAND | wx.TOP, 8)
        cap_grid = wx.FlexGridSizer(4, 2, 6, 10)
        cap_grid.AddGrowableCol(1, 1)
        self._lbl_cap_eq  = self._result_row(panel, cap_grid, "Capacité réelle / équipe")
        self._lbl_cap_day = self._result_row(panel, cap_grid, "Capacité réelle / jour")
        self._lbl_cap_yr  = self._result_row(panel, cap_grid, "Capacité réelle / an")
        self._lbl_charge  = self._result_row(panel, cap_grid, "Taux de charge global")
        sizer.Add(cap_grid, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        return panel

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

    def _build_tab_investissements(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # CAPEX
        sizer.Add(_section_label(panel, "CAPEX – Investissements machines / équipements"), 0, wx.EXPAND | wx.TOP, 6)

        mg_sizer = wx.BoxSizer(wx.HORIZONTAL)
        mg_sizer.Add(wx.StaticText(panel, label=" Durée amort. = durée programme :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._lbl_capex_years = wx.StaticText(panel, label="—")
        self._lbl_capex_years.SetBackgroundColour(RESULT_BG)
        font_cy = self._lbl_capex_years.GetFont()
        font_cy.SetWeight(wx.FONTWEIGHT_BOLD)
        self._lbl_capex_years.SetFont(font_cy)
        mg_sizer.Add(self._lbl_capex_years, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        mg_sizer.Add(wx.StaticText(panel, label=" ans  (réglable dans Hypothèses)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        mg_sizer.Add(wx.StaticText(panel, label="   Marge globale CAPEX (%) :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 16)
        self.e_capex_margin = wx.SpinCtrlDouble(panel, min=0, max=100, initial=15, inc=1, size=(80, -1))
        self.e_capex_margin.Bind(wx.EVT_SPINCTRLDOUBLE, self._on_param_changed)
        mg_sizer.Add(self.e_capex_margin, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        sizer.Add(mg_sizer, 0, wx.TOP | wx.BOTTOM, 4)

        self.capex_table = CapexTable(panel, on_change=self._on_table_changed,
                                      serie_ref=self._get_serie_data)
        sizer.Add(self.capex_table, 2, wx.EXPAND | wx.ALL, 6)

        # Tooling
        sizer.Add(_section_label(panel, "Tooling – Outillages & électrodes"), 0, wx.EXPAND | wx.TOP, 8)
        self.tooling_table = ToolingTable(panel, on_change=self._on_table_changed)
        sizer.Add(self.tooling_table, 2, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(sizer)
        return panel

    # ------------------------------------------------------------------ tab 3 : capacité & coûts

    def _build_tab_capacite(self, parent):
        panel = wx.ScrolledWindow(parent, style=wx.VSCROLL)
        panel.SetScrollRate(0, 20)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Machine posts — linked to project operations
        sizer.Add(_section_label(panel, "Capacité par poste machine (liés aux Opérations)"), 0, wx.EXPAND | wx.TOP, 6)
        self.machine_table = MachineTable(panel, on_change=self._on_machines_changed,
                                          serie_ref=self._get_serie_data)
        sizer.Add(self.machine_table, 3, wx.EXPAND | wx.ALL, 6)

        # Setup
        sizer.Add(_section_label(panel, "Setup / Démarrage série"), 0, wx.EXPAND | wx.TOP, 8)
        setup_grid = wx.FlexGridSizer(6, 3, 6, 10)
        setup_grid.AddGrowableCol(1, 1)
        self.e_setup_mount  = self._hyp_row(panel, setup_grid, "Temps montage outillage",   "1.0",  "h")
        self.e_setup_sop    = self._hyp_row(panel, setup_grid, "Validation SOP / 1er art.", "0.5",  "h")
        self.e_lot          = self._hyp_row(panel, setup_grid, "Taille de lot / campagne",  "5000", "pcs")
        self.e_setup_margin = self._hyp_row(panel, setup_grid, "Marge setup (%)",           "15.0", "%")

        self._lbl_campaigns = self._result_row(panel, setup_grid, "Campagnes / an")
        self._lbl_setup_pc  = self._result_row(panel, setup_grid, "Setup amorti / pièce (prix)")
        sizer.Add(setup_grid, 0, wx.EXPAND | wx.ALL, 8)

        # Contrôle
        sizer.Add(_section_label(panel, "Contrôle de production"), 0, wx.EXPAND | wx.TOP, 8)
        ctrl_grid = wx.FlexGridSizer(6, 3, 6, 10)
        ctrl_grid.AddGrowableCol(1, 1)
        self.e_spc_freq  = self._hyp_row(panel, ctrl_grid, "Fréquence SPC (1/N pcs)",   "50",  "")
        self.e_spc_time  = self._hyp_row(panel, ctrl_grid, "Temps contrôle SPC (min)",  "2.0", "min/pcs mesuré")
        self.e_ctrl100_t = self._hyp_row(panel, ctrl_grid, "Temps contrôle 100% (s)",   "3.0", "s/pcs")
        self.e_ctrl_mode = self._hyp_row(panel, ctrl_grid, "Mode (SPC ou 100%)",         "SPC", "")

        self._lbl_ctrl_spc = self._result_row(panel, ctrl_grid, "Coût SPC / pièce produite")
        self._lbl_ctrl_100 = self._result_row(panel, ctrl_grid, "Coût 100% / pièce")
        sizer.Add(ctrl_grid, 0, wx.EXPAND | wx.ALL, 8)

        # Achats / logistique
        sizer.Add(_section_label(panel, "Achats & Logistique"), 0, wx.EXPAND | wx.TOP, 8)
        buy_grid = wx.FlexGridSizer(4, 3, 6, 10)
        buy_grid.AddGrowableCol(1, 1)
        self.e_mat_cost   = self._hyp_row(panel, buy_grid, "Matières / pièce",      "0.0", "€/pcs")
        self.e_mat_margin = self._hyp_row(panel, buy_grid, "Marge matières (%)",    "10.0", "%")
        self.e_log_cost   = self._hyp_row(panel, buy_grid, "Logistique / pièce",   "0.0", "€/pcs")
        self.e_log_margin = self._hyp_row(panel, buy_grid, "Marge logistique (%)", "5.0",  "%")
        sizer.Add(buy_grid, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        return panel

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

    def load_project(self, project: Project):
        self.project = project
        self._building = True
        try:
            active = project.serie_data is not None
            self._set_active(active)
            if active:
                # Synchronise les postes machine depuis les opérations du projet
                project.serie_data.sync_from_project(project)
                self._load_fields(project.serie_data)
                self._refresh_computed()
                if self._eur_usd_rate is None:
                    self._fetch_eur_usd_rate()
        finally:
            self._building = False

    def refresh_data(self):
        """Appelé depuis MainFrame quand les opérations du projet changent."""
        if not self.project or not self.project.serie_data:
            return
        self._building = True
        try:
            self.project.serie_data.sync_from_project(self.project)
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
        self.e_fallback_tc.ChangeValue(str(sd.fallback_cycle_time_s))
        self.e_mo_prod.ChangeValue(str(sd.mo_production_rate))
        self.e_mo_qual.ChangeValue(str(sd.mo_quality_rate))
        self.e_overhead.ChangeValue(str(sd.overhead_coef))

        self._lbl_capex_years.SetLabel(str(sd.program_lifetime_years))
        self.e_capex_margin.SetValue(sd.capex_global_margin * 100)
        self.capex_table.set_items(sd.capex_items)
        self.tooling_table.set_items(sd.tooling_items)
        self.machine_table.set_items(sd.machine_posts)

        self.e_setup_mount.ChangeValue(str(sd.tooling_setup_time_h))
        self.e_setup_sop.ChangeValue(str(sd.sop_validation_time_h))
        self.e_lot.ChangeValue(str(sd.lot_size))
        self.e_setup_margin.ChangeValue(str(sd.setup_margin * 100))

        self.e_spc_freq.ChangeValue(str(sd.spc_frequency))
        self.e_spc_time.ChangeValue(str(sd.spc_time_per_piece_min))
        self.e_ctrl100_t.ChangeValue(str(sd.control_100pct_time_s))
        self.e_ctrl_mode.ChangeValue(sd.control_mode)

        self.e_mat_cost.ChangeValue(str(sd.material_cost_per_piece))
        self.e_mat_margin.ChangeValue(str(sd.material_margin * 100))
        self.e_log_cost.ChangeValue(str(sd.logistics_cost_per_piece))
        self.e_log_margin.ChangeValue(str(sd.logistics_margin * 100))

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

        # Récupère les postes existants avec machines_available mis à jour par MachineTable
        machine_posts = self.machine_table.get_items()

        sd = SerieData(
            annual_volume=i(self.e_volume, 100000),
            working_days_per_year=i(self.e_days, 220),
            shifts_per_day=i(self.e_shifts, 2),
            hours_per_shift=f(self.e_hshift, 7.0),
            trs=f(self.e_trs, 0.85),
            scrap_rate=min(f(self.e_scrap_rate, 0.0) / 100.0, 0.99),
            program_lifetime_years=max(1, i(self.e_program_years, 5)),
            fallback_cycle_time_s=f(self.e_fallback_tc, 0.0),
            mo_production_rate=f(self.e_mo_prod, 28.0),
            mo_quality_rate=f(self.e_mo_qual, 28.0),
            overhead_coef=f(self.e_overhead, 0.30),
            capex_items=self.capex_table.get_items(),
            capex_global_margin=self.e_capex_margin.GetValue() / 100.0,
            tooling_items=self.tooling_table.get_items(),
            machine_posts=machine_posts,
            tooling_setup_time_h=f(self.e_setup_mount, 1.0),
            sop_validation_time_h=f(self.e_setup_sop, 0.5),
            lot_size=i(self.e_lot, 5000),
            setup_margin=f(self.e_setup_margin, 15.0) / 100.0,
            spc_frequency=i(self.e_spc_freq, 50),
            spc_time_per_piece_min=f(self.e_spc_time, 2.0),
            control_100pct_time_s=f(self.e_ctrl100_t, 3.0),
            control_mode=self.e_ctrl_mode.GetValue().strip() or "SPC",
            material_cost_per_piece=f(self.e_mat_cost, 0.0),
            material_margin=f(self.e_mat_margin, 10.0) / 100.0,
            logistics_cost_per_piece=f(self.e_log_cost, 0.0),
            logistics_margin=f(self.e_log_margin, 5.0) / 100.0,
            global_commercial_margin=self.e_global_margin.GetValue() / 100.0,
        )
        return sd

    def _refresh_computed(self):
        """Met à jour les labels de résultats et la grille de synthèse."""
        if not self.project or not self.project.serie_data:
            return
        sd = self.project.serie_data

        # -- Rebut --
        prod_vol   = sd.production_volume_per_year()
        scrap_vol  = sd.scrap_units_per_year()
        self._lbl_prod_vol .SetLabel(f"{prod_vol:,.0f}  pcs/an")
        self._lbl_scrap_vol.SetLabel(
            f"{scrap_vol:,.0f}  pcs/an" if scrap_vol > 0 else "—  (pas de rebut)")

        # -- Goulot TC --
        tc_goulot = sd.get_target_cycle_time_s()
        if tc_goulot > 0:
            self._lbl_goulot.SetLabel(f"{tc_goulot:.2f}")
        else:
            self._lbl_goulot.SetLabel("—  (aucune opération interne active)")

        # -- Tab 1 computed --
        cap_eq  = sd.real_capacity_per_shift()
        cap_day = cap_eq * sd.shifts_per_day
        cap_yr  = sd.real_capacity_per_year()
        charge  = sd.load_rate()
        self._lbl_cap_eq .SetLabel(f"{cap_eq:,.0f}  pcs/équipe")
        self._lbl_cap_day.SetLabel(f"{cap_day:,.0f}  pcs/jour")
        self._lbl_cap_yr .SetLabel(f"{cap_yr:,.0f}  pcs/an")
        charge_txt = f"{charge*100:.1f} %"
        if charge > 0.85:
            self._lbl_charge.SetForegroundColour(wx.RED)
        else:
            self._lbl_charge.SetForegroundColour(wx.Colour(0, 140, 0))
        self._lbl_charge.SetLabel(charge_txt)

        # -- Tab 3 computed --
        self._lbl_campaigns.SetLabel(f"{sd.campaigns_per_year():.1f}  campagnes/an")
        self._lbl_setup_pc .SetLabel(f"{sd.setup_price_per_piece():.4f}  €/pcs")
        self._lbl_ctrl_spc .SetLabel(f"{sd.spc_cost_per_piece():.4f}  €/pcs")
        self._lbl_ctrl_100 .SetLabel(f"{sd.control_100pct_cost_per_piece():.4f}  €/pcs")

        # -- Refresh machine table --
        self.machine_table.set_items(sd.machine_posts)
        self.capex_table.set_items(sd.capex_items)
        self._lbl_capex_years.SetLabel(str(sd.program_lifetime_years))

        # -- Tab 4 synthèse --
        self._refresh_synthese(sd)

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
            ("Matières premières",
             sd.material_cost_per_piece,
             sd.material_cost_per_piece * (1 + sd.material_margin)),
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
            grid.SetCellValue(r, 1, f"{cost:.4f} €")
            grid.SetCellValue(r, 2, f"{price:.4f} €")
            grid.SetCellValue(r, 3, f"{pct:.1f} %")
            grid.SetCellAlignment(r, 1, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            grid.SetCellAlignment(r, 2, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            grid.SetCellAlignment(r, 3, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)

        r_sub = len(rows)
        grid.SetCellValue(r_sub, 0, "SOUS-TOTAL (avant marge commerciale)")
        grid.SetCellValue(r_sub, 1, f"{total_cost:.4f} €")
        grid.SetCellValue(r_sub, 2, f"{subtotal_price:.4f} €")
        grid.SetCellValue(r_sub, 3, "—")
        for c in range(4):
            grid.SetCellBackgroundColour(r_sub, c, TOTAL_BG)
            grid.SetCellFont(r_sub, c,
                             wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        r_tot = len(rows) + 1
        grid.SetCellValue(r_tot, 0, f"PRIX DE VENTE (marge ciale {sd.global_commercial_margin*100:.0f}%)")
        grid.SetCellValue(r_tot, 1, "")
        grid.SetCellValue(r_tot, 2, f"{pv:.4f} €")
        grid.SetCellValue(r_tot, 3, "100 %")
        for c in range(4):
            grid.SetCellBackgroundColour(r_tot, c, wx.Colour(30, 90, 160))
            grid.SetCellTextColour(r_tot, c, wx.WHITE)
            grid.SetCellFont(r_tot, c,
                             wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        grid.AutoSizeColumns()
        grid.EndBatch()

        self.lbl_pv.SetLabel(f"{pv:.4f} €")
        self.lbl_ca.SetLabel(f"{sd.annual_revenue():,.0f} €/an")

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
            self._refresh_computed()
            if self._eur_usd_rate is None:
                self._fetch_eur_usd_rate()
        elif not active and self.project:
            self.project.serie_data = None
        self._set_active(active)
        self._notify()

    def _on_param_changed(self, event):
        if self._building:
            event.Skip()
            return
        self._commit_to_model()
        event.Skip()

    def _on_table_changed(self):
        self._commit_to_model()

    def _on_machines_changed(self):
        """Appelé quand machines_available est modifié dans MachineTable.

        Ne re-sync pas depuis les opérations (ce qui écraserait l'édition).
        Met à jour le projet avec les machines_available édités.
        """
        if not self.project or not self.project.serie_data:
            return
        # Update machines_available in the existing posts from UI
        self.project.serie_data.machine_posts = self.machine_table.get_items()
        self._refresh_computed()
        self._notify()

    def _commit_to_model(self):
        if not self.project or not self.project.serie_data:
            return
        new_sd = self._collect_serie_data()
        self.project.serie_data = new_sd
        self._refresh_computed()
        self._notify()

    def _notify(self):
        if self.on_serie_updated:
            self.on_serie_updated()

    # ------------------------------------------------------------------ helpers

    def _set_active(self, active: bool):
        self.toggle.SetValue(active)
        if active:
            self.lbl_status.SetLabel("Mode Série actif")
            self.lbl_status.SetForegroundColour(wx.Colour(30, 120, 30))
        else:
            self.lbl_status.SetLabel("Mode Série non activé pour ce projet")
            self.lbl_status.SetForegroundColour(wx.Colour(120, 120, 120))
        self.nb.Show(active)
        self.Layout()

    # ------------------------------------------------------------------ EUR/USD

    def _fetch_eur_usd_rate(self):
        """Récupère le taux EUR/USD en arrière-plan (API Frankfurter, données BCE)."""
        import threading

        self._lbl_rate.SetLabel("EUR/USD : chargement…")
        self._btn_rate.Disable()

        def _worker():
            try:
                import urllib.request
                import json
                url = "https://api.frankfurter.app/latest?from=EUR&to=USD"
                req = urllib.request.Request(url, headers={"User-Agent": "MWQuote/1.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = json.loads(resp.read().decode())
                rate = float(data["rates"]["USD"])
                date = data.get("date", "")
                wx.CallAfter(self._on_rate_fetched, rate, date)
            except Exception as exc:
                wx.CallAfter(self._on_rate_error, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_rate_fetched(self, rate: float, date: str):
        self._eur_usd_rate = rate
        self._rate_date = date
        self._lbl_rate.SetLabel(f"1 EUR = {rate:.4f} USD   ({date}, BCE via Frankfurter)")
        self._btn_rate.Enable()
        self._refresh_usd_price()

    def _on_rate_error(self, msg: str):
        self._lbl_rate.SetLabel(f"EUR/USD : erreur — {msg[:60]}")
        self._btn_rate.Enable()

    def _refresh_usd_price(self):
        if not self.project or not self.project.serie_data:
            self.lbl_pv_usd.SetLabel("— USD")
            return
        pv = self.project.serie_data.selling_price_per_piece()
        if self._eur_usd_rate and pv > 0:
            self.lbl_pv_usd.SetLabel(f"{pv * self._eur_usd_rate:.4f} USD")
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
