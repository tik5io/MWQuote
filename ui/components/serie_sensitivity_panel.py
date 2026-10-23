# ui/components/serie_sensitivity_panel.py
"""Sensibilité du prix série au temps par pièce et au taux horaire de chaque étape.

Temps par pièce = temps de cycle ÷ nombre de pièces simultanées.
Une ligne par étape interne de la phase Série : deux curseurs (±100 % autour de
la valeur actuelle) pour le temps par pièce et le taux horaire, le prix série
recalculé en direct, et un graphique iso-prix temps × taux pour l'étape choisie.
Rien n'est modifié tant que l'on n'a pas cliqué sur « Appliquer ».
"""
import wx

from domain.cost import CostType
from domain.operation import SUBCONTRACTING_TYPOLOGY, TOOLING_TYPOLOGY

ISO_STEPS = (-0.20, -0.10, -0.05, 0.0, 0.10)   # courbes iso-prix (écart vs prix simulé)


def _eur(v, d=4):
    return f"{v:,.{d}f} €".replace(",", " ")


class _Step:
    """Étape interne et ses valeurs série (base = valeurs actuelles enregistrées)."""

    def __init__(self, op, cost):
        self.op = op
        self.cost = cost
        self.pieces = cost.serie_pieces()              # pièces simultanées par cycle
        self.time0 = cost.serie_cycle_s() / self.pieces  # temps par pièce (s)
        self.rate0 = cost.serie_rate()
        self.time_pct = 0
        self.rate_pct = 0

    @property
    def label(self):
        return f"{self.op.label} › {self.cost.name}"

    @property
    def time(self):
        """Temps par pièce simulé (s)."""
        return self.time0 * (1 + self.time_pct / 100.0)

    @property
    def cycle(self):
        """Temps de cycle correspondant (s) = temps par pièce × pièces simultanées."""
        return self.time * self.pieces

    @property
    def rate(self):
        return self.rate0 * (1 + self.rate_pct / 100.0)

    @property
    def moved(self):
        return self.time_pct != 0 or self.rate_pct != 0


class IsoPriceChart(wx.Panel):
    """Plan temps par pièce (x) × taux (y) de l'étape choisie, avec courbes iso-prix série."""

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.data = None
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))

    def set_data(self, data):
        """data = dict(step, k, p_other, p_base, p_sim) ; prix = p_other + k·temps/pc·taux."""
        self.data = data
        self.Refresh()

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        self.draw(dc, w, h)

    def render_bitmap(self, w, h) -> wx.Bitmap:
        """Rendu hors écran (export / contrôle visuel)."""
        bmp = wx.Bitmap(w, h)
        dc = wx.MemoryDC(bmp)
        self.draw(dc, w, h)
        dc.SelectObject(wx.NullBitmap)
        return bmp

    def draw(self, dc, w, h):
        dc.SetBackground(wx.Brush(wx.WHITE))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        d = self.data
        font = wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        bold = wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        if not d or d["step"].time0 <= 0 or d["step"].rate0 <= 0 or d["k"] <= 0:
            gc.SetFont(font, wx.Colour(130, 130, 130))
            gc.DrawText("Sélectionnez une étape avec un temps par pièce et un taux non nuls.", 12, 12)
            return
        step, k, p_other = d["step"], d["k"], d["p_other"]
        ml, mr, mt, mb = 60, 20, 30, 40
        cw, ch = w - ml - mr, h - mt - mb
        if cw < 60 or ch < 60:
            return
        x_max, y_max = 2 * step.time0, 2 * step.rate0

        def to_px(tc, rate):
            return ml + tc / x_max * cw, mt + ch - rate / y_max * ch

        gc.SetFont(bold, wx.Colour(40, 40, 40))
        pieces = f" — TC ÷ {step.pieces:g} pièces simultanées" if step.pieces != 1 else ""
        gc.DrawText(f"Prix série selon temps par pièce × taux — {step.label}{pieces}", ml, 6)

        # Axes et graduations
        gc.SetPen(wx.Pen(wx.Colour(180, 180, 180), 1))
        gc.StrokeLine(ml, mt + ch, ml + cw, mt + ch)
        gc.StrokeLine(ml, mt, ml, mt + ch)
        gc.SetFont(font, wx.Colour(90, 90, 90))
        for i in range(5):
            tc = x_max * i / 4
            x, _ = to_px(tc, 0)
            gc.DrawText(f"{tc:.1f}" if x_max < 10 else f"{tc:.0f}", x - 8, mt + ch + 4)
            rate = y_max * i / 4
            _, y = to_px(0, rate)
            gc.DrawText(f"{rate:.0f}", ml - 34, y - 7)
        gc.DrawText("Temps par pièce (s) = temps de cycle ÷ pièces simultanées", ml + cw / 2 - 150, mt + ch + 20)
        gc.DrawText("€/h", 8, mt - 4)

        # Courbes iso-prix : temps/pc × taux = (P - p_other) / k, les autres étapes
        # restant à leurs valeurs simulées. Les écarts se lisent depuis le prix simulé
        # (la courbe « simulé » passe toujours par le point rouge) ; le prix actuel
        # enregistré est ajouté s'il diffère.
        p_sim, p_base = d["p_sim"], d["p_base"]
        curves = [(f"{delta * 100:+.0f} % vs simulé", p_sim * (1 + delta),
                   wx.Colour(40, 140, 60) if delta < 0 else wx.Colour(200, 90, 40), 1, wx.PENSTYLE_SHORT_DASH)
                  for delta in ISO_STEPS if delta != 0]
        curves.append(("simulé", p_sim, wx.Colour(200, 50, 50), 2, wx.PENSTYLE_SOLID))
        if abs(p_sim - p_base) > 1e-9:
            curves.append(("prix actuel", p_base, wx.Colour(30, 90, 160), 2, wx.PENSTYLE_SOLID))
        hidden = []
        for name, target, colour, width, style in curves:
            product = (target - p_other) / k
            if product <= 0:
                hidden.append(f"{name} ({target:.2f} €) : inatteignable avec cette seule étape")
                continue
            gc.SetPen(wx.Pen(colour, width, style))
            path = gc.CreatePath()
            started = False
            label_pt = None
            for i in range(1, 201):
                tc = x_max * i / 200
                rate = product / tc
                if rate > y_max:
                    continue
                x, y = to_px(tc, rate)
                if not started:
                    path.MoveToPoint(x, y)
                    started = True
                else:
                    path.AddLineToPoint(x, y)
                label_pt = (x, y)   # extrémité droite : étiquettes bien séparées
            if started:
                gc.StrokePath(path)
                gc.SetFont(font, colour)
                label = f"{name} ({target:.2f} €)"
                tw, th = gc.GetTextExtent(label)
                gc.DrawText(label, label_pt[0] - tw - 2, max(label_pt[1] - th - 1, mt))
            else:
                hidden.append(f"{name} ({target:.2f} €) : hors cadre (±100 % de l'étape)")

        # Courbes non visibles : signalées plutôt que perdues
        gc.SetFont(font, wx.Colour(120, 120, 120))
        for n, text in enumerate(hidden):
            gc.DrawText(text, ml + 8, mt + 4 + n * 14)

        # Point actuel (creux) et point simulé (plein)
        bx, by = to_px(step.time0, step.rate0)
        sx, sy = to_px(step.time, step.rate)
        gc.SetPen(wx.Pen(wx.Colour(30, 90, 160), 2))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.DrawEllipse(bx - 6, by - 6, 12, 12)
        if step.moved:
            gc.SetPen(wx.Pen(wx.Colour(120, 120, 120), 1, wx.PENSTYLE_DOT))
            gc.StrokeLine(bx, by, sx, sy)
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(220, 60, 60)))
        gc.DrawEllipse(sx - 5, sy - 5, 10, 10)
        gc.SetFont(font, wx.Colour(160, 40, 40))
        gc.DrawText(f"simulé : {step.time:.2f} s/pc · {step.rate:.0f} €/h → {d['p_sim']:.3f} €/pc",
                    min(sx + 8, ml + cw - 230), max(sy - 18, mt))


TIME_COLOUR = wx.Colour(0, 140, 150)    # effet temps
RATE_COLOUR = wx.Colour(130, 80, 170)   # effet taux


class GainWaterfallChart(wx.Panel):
    """Cascade horizontale : prix actuel → contribution de chaque étape modifiée → prix simulé.

    Chaque étape est découpée en effet temps (Δtemps × taux actuel) et effet
    taux (temps simulé × Δtaux) ; la somme des deux est l'écart de l'étape.
    """

    ROW_H = 24

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.data = None
        self.on_select = None      # callback(index d'étape) au clic sur une barre
        self._hit = []             # (y0, y1, index d'étape)
        self.Bind(wx.EVT_PAINT, lambda e: self.draw(wx.AutoBufferedPaintDC(self), *self.GetClientSize()))
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))
        self.Bind(wx.EVT_LEFT_DOWN, self._on_click)

    def set_data(self, data):
        """data = dict(p_base, p_sim, items=[dict(idx, label, d_time, d_rate)], residual)."""
        self.data = data
        self.Refresh()

    def render_bitmap(self, w, h) -> wx.Bitmap:
        bmp = wx.Bitmap(w, h)
        dc = wx.MemoryDC(bmp)
        self.draw(dc, w, h)
        dc.SelectObject(wx.NullBitmap)
        return bmp

    def _on_click(self, event):
        y = event.GetY()
        for y0, y1, idx in self._hit:
            if y0 <= y <= y1 and callable(self.on_select):
                self.on_select(idx)
                return

    def draw(self, dc, w, h):
        dc.SetBackground(wx.Brush(wx.WHITE))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        font = wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        bold = wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        self._hit = []
        gc.SetFont(bold, wx.Colour(40, 40, 40))
        gc.DrawText("D'où vient l'écart de prix série ? (€/pc)", 10, 6)
        d = self.data
        if not d or not d["items"]:
            gc.SetFont(font, wx.Colour(130, 130, 130))
            gc.DrawText("Bougez des curseurs : chaque étape modifiée apparaîtra ici avec sa part du gain.", 10, 30)
            return

        rows = [("Prix actuel", None, d["p_base"])]
        rows += [(it["label"], it, None) for it in d["items"]]
        if abs(d["residual"]) > 1e-6:
            rows.append(("Autres effets (non linéaires)", dict(d_time=d["residual"], d_rate=0.0, idx=None, residual=True), None))
        rows.append(("Prix simulé", None, d["p_sim"]))

        # Bornes de l'axe (zoom sur la zone utile, axe tronqué)
        levels, cum = [d["p_base"]], d["p_base"]
        for _, it, _ in rows[1:-1]:
            cum += it["d_time"] + it["d_rate"]
            levels.append(cum)
        lo, hi = min(levels + [d["p_sim"]]), max(levels + [d["p_sim"]])
        span = max(hi - lo, abs(d["p_base"]) * 0.01, 1e-6)
        x_lo, x_hi = lo - span * 0.25, hi + span * 0.25

        label_w, value_w, mt = int(min(220, w * 0.28)), 175, 30
        cw = w - label_w - value_w - 20
        if cw < 80:
            return
        row_h = min(self.ROW_H, max(14, (h - mt - 30) // max(len(rows), 1)))

        def to_x(v):
            return label_w + (v - x_lo) / (x_hi - x_lo) * cw

        total_gain = d["p_sim"] - d["p_base"]
        cum = d["p_base"]
        for n, (label, it, total) in enumerate(rows):
            y = mt + n * row_h
            bar_y, bar_h = y + 3, row_h - 6
            gc.SetFont(bold if it is None else font, wx.Colour(40, 40, 40))
            max_chars = max(12, label_w // 6)
            text = label if len(label) <= max_chars else label[:max_chars - 1] + "…"
            gc.DrawText(text, 8, y + (row_h - 12) / 2)
            if it is None:
                # Totaux : barre depuis le bord gauche (axe tronqué)
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.SetBrush(wx.Brush(wx.Colour(30, 90, 160) if n == 0 else wx.Colour(200, 50, 50)))
                gc.DrawRectangle(label_w, bar_y, to_x(total) - label_w, bar_h)
                gc.SetFont(bold, wx.Colour(40, 40, 40))
                gc.DrawText(f"{total:.4f} €", label_w + cw + 8, y + (row_h - 12) / 2)
                if n:
                    pct = total_gain / d["p_base"] * 100 if d["p_base"] else 0
                    gc.SetFont(font, wx.Colour(30, 130, 50) if total_gain < 0 else wx.Colour(190, 60, 30))
                    gc.DrawText(f"{total_gain:+.4f} € · {pct:+.1f} %", label_w + cw + 75, y + (row_h - 12) / 2)
                continue
            # Étape : segment temps puis segment taux, à partir du niveau cumulé
            start = cum
            for delta, colour in ((it["d_time"], TIME_COLOUR), (it["d_rate"], RATE_COLOUR)):
                if abs(delta) < 1e-12:
                    continue
                x0, x1 = to_x(start), to_x(start + delta)
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.SetBrush(wx.Brush(wx.Colour(150, 150, 150) if it.get("residual") else colour))
                gc.DrawRectangle(min(x0, x1), bar_y, max(abs(x1 - x0), 1), bar_h)
                start += delta
            # Liaison pointillée vers la ligne suivante
            gc.SetPen(wx.Pen(wx.Colour(160, 160, 160), 1, wx.PENSTYLE_DOT))
            gc.StrokeLine(to_x(start), bar_y + bar_h, to_x(start), bar_y + bar_h + 6)
            step_delta = it["d_time"] + it["d_rate"]
            share = step_delta / total_gain * 100 if abs(total_gain) > 1e-12 else 0
            gc.SetFont(font, wx.Colour(30, 130, 50) if step_delta < 0 else wx.Colour(190, 60, 30))
            gc.DrawText(f"{step_delta:+.4f} €  ·  {share:.0f} %", label_w + cw + 8, y + (row_h - 12) / 2)
            if it.get("idx") is not None:
                self._hit.append((y, y + row_h, it["idx"]))
            cum = start

        # Légende
        ly = mt + len(rows) * row_h + 6
        gc.SetFont(font, wx.Colour(90, 90, 90))
        for n, (txt, colour) in enumerate((("effet temps", TIME_COLOUR), ("effet taux", RATE_COLOUR))):
            x = label_w + n * 110
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(wx.Brush(colour))
            gc.DrawRectangle(x, ly + 2, 12, 10)
            gc.DrawText(txt, x + 16, ly)
        gc.DrawText("% = part de l'écart total · axe tronqué · clic = graphique de l'étape", label_w, ly + 16)


class SerieSensitivityPanel(wx.Panel):
    """Curseurs temps par pièce / taux par étape et prix série compilé en direct."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.phase = None
        self.steps = []
        self.selected = 0
        self.on_applied = None   # callback après « Appliquer »
        self._p_base = 0.0
        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = wx.BoxSizer(wx.VERTICAL)

        top = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_base = wx.StaticText(self, label="Prix série actuel : —")
        self.lbl_sim = wx.StaticText(self, label="")
        f = self.lbl_sim.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        f.SetPointSize(f.GetPointSize() + 2)
        self.lbl_sim.SetFont(f)
        top.Add(self.lbl_base, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        top.Add(self.lbl_sim, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        top.AddStretchSpacer(1)
        self.btn_reset = wx.Button(self, label="Réinitialiser")
        self.btn_reset.Bind(wx.EVT_BUTTON, lambda e: self._reset_sliders())
        self.btn_apply = wx.Button(self, label="Appliquer à la série")
        self.btn_apply.SetToolTip("Enregistre les temps et taux simulés comme valeurs Série des étapes\n"
                                  "(temps de cycle = temps par pièce × pièces simultanées).\n"
                                  "Le chiffrage Proto n'est pas modifié.")
        self.btn_apply.Bind(wx.EVT_BUTTON, self._on_apply)
        top.Add(self.btn_reset, 0, wx.ALL, 4)
        top.Add(self.btn_apply, 0, wx.ALL, 4)
        root.Add(top, 0, wx.EXPAND)

        hint = wx.StaticText(self, label=(
            "Temps par pièce = temps de cycle ÷ pièces simultanées. Curseurs : ±100 % autour de la valeur série actuelle. "
            "« €/pc par s » et « €/pc par 10 €/h » : gain de prix pour 1 s par pièce ou 10 €/h de taux en moins. "
            "Cliquez une étape pour le graphique."))
        hint.SetForegroundColour(wx.Colour(100, 100, 100))
        root.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        self.rows_panel = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.HSCROLL | wx.BORDER_THEME)
        self.rows_panel.SetScrollRate(20, 20)
        self.rows_sizer = wx.FlexGridSizer(cols=9, hgap=8, vgap=4)
        self.rows_sizer.AddGrowableCol(2, 1)
        self.rows_sizer.AddGrowableCol(5, 1)
        self.rows_panel.SetSizer(self.rows_sizer)
        root.Add(self.rows_panel, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        charts = wx.BoxSizer(wx.HORIZONTAL)
        self.waterfall = GainWaterfallChart(self)
        self.waterfall.SetMinSize((-1, 260))
        self.waterfall.on_select = self._select
        charts.Add(self.waterfall, 3, wx.EXPAND | wx.RIGHT, 6)
        self.chart = IsoPriceChart(self)
        self.chart.SetMinSize((-1, 260))
        charts.Add(self.chart, 2, wx.EXPAND)
        root.Add(charts, 1, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(root)

    def _header(self):
        for text in ("Étape", "Temps/pc actuel", "Temps par pièce", "Temps/pc simulé",
                     "Taux actuel", "Taux horaire", "Taux simulé", "€/pc par s", "€/pc par 10 €/h"):
            t = wx.StaticText(self.rows_panel, label=text)
            t.SetFont(t.GetFont().Bold())
            self.rows_sizer.Add(t, 0, wx.ALIGN_CENTER_VERTICAL)

    # ------------------------------------------------------------------ données

    def load(self, project):
        self.project = project
        phase = project.current_phase if project else None
        self.phase = phase if phase is not None and phase.is_serie and phase.serie_data else None
        self.steps = []
        if self.phase is not None:
            for op in project.current_version.operations:
                if op.typology in (SUBCONTRACTING_TYPOLOGY, TOOLING_TYPOLOGY):
                    continue
                for cost in op.costs.values():
                    if cost.cost_type == CostType.INTERNAL_OPERATION and cost.is_active:
                        self.steps.append(_Step(op, cost))
        self.selected = min(self.selected, max(len(self.steps) - 1, 0))
        self._build_rows()
        self._recompute()

    def _build_rows(self):
        self.rows_panel.Freeze()
        self.rows_sizer.Clear(delete_windows=True)
        self._widgets = []
        if not self.steps:
            self.rows_sizer.Add(wx.StaticText(self.rows_panel, label="Aucune étape interne dans cette phase."))
        else:
            self._header()
        for idx, step in enumerate(self.steps):
            name = wx.StaticText(self.rows_panel, label="  " + step.label, size=(250, -1),
                                 style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
            name.SetToolTip(step.label)
            name.SetCursor(wx.Cursor(wx.CURSOR_HAND))
            name.Bind(wx.EVT_LEFT_DOWN, lambda e, i=idx: self._select(i))
            tc0 = wx.StaticText(self.rows_panel, label=f"{step.time0:.2f} s")
            tc0.SetToolTip(f"Temps de cycle {step.time0 * step.pieces:.1f} s ÷ {step.pieces:g} pièce(s) simultanée(s)")
            s_tc = wx.Slider(self.rows_panel, value=0, minValue=-100, maxValue=100, size=(120, -1))
            tc_sim = wx.StaticText(self.rows_panel, label="", size=(170, -1), style=wx.ST_NO_AUTORESIZE)
            r0 = wx.StaticText(self.rows_panel, label=f"{step.rate0:.0f} €/h")
            s_rate = wx.Slider(self.rows_panel, value=0, minValue=-100, maxValue=100, size=(120, -1))
            r_sim = wx.StaticText(self.rows_panel, label="", size=(120, -1), style=wx.ST_NO_AUTORESIZE)
            d_tc = wx.StaticText(self.rows_panel, label="", size=(80, -1), style=wx.ST_NO_AUTORESIZE)
            d_rate = wx.StaticText(self.rows_panel, label="", size=(110, -1), style=wx.ST_NO_AUTORESIZE)
            for wdg in (s_tc, s_rate):
                wdg.Bind(wx.EVT_SLIDER, lambda e, i=idx: self._on_slider(i))
                wdg.Bind(wx.EVT_SET_FOCUS, lambda e, i=idx: (self._select(i), e.Skip()))
            for wdg in (name, tc0, s_tc, tc_sim, r0, s_rate, r_sim, d_tc, d_rate):
                self.rows_sizer.Add(wdg, 0, wx.ALIGN_CENTER_VERTICAL | (wx.EXPAND if isinstance(wdg, wx.Slider) else 0))
            self._widgets.append(dict(name=name, s_tc=s_tc, tc_sim=tc_sim, s_rate=s_rate,
                                      r_sim=r_sim, d_tc=d_tc, d_rate=d_rate))
        self.rows_panel.FitInside()
        self.rows_panel.Thaw()
        self.Layout()

    def _factor(self):
        """€/pc pour 1 s·€/h de (temps par pièce × taux) — MO linéaire."""
        sd = self.phase.serie_data
        return (1.0 + sd.overhead_coef) * sd.scrap_factor() * (1.0 + sd.global_commercial_margin) / 3600.0

    def _overrides(self):
        return {id(s.cost): {"cycle_s": s.cycle, "rate": s.rate} for s in self.steps if s.moved}

    def _recompute(self):
        if self.phase is None:
            self.lbl_base.SetLabel("La vue de sensibilité porte sur une phase Série.")
            self.lbl_sim.SetLabel("")
            self.chart.set_data(None)
            self.waterfall.set_data(None)
            self.btn_apply.Enable(False)
            self.btn_reset.Enable(False)
            return
        sd = self.phase.serie_data
        self._p_base = sd.price_with_overrides(self.project, self.phase, {})
        p_sim = sd.price_with_overrides(self.project, self.phase, self._overrides())
        delta = p_sim - self._p_base
        self.lbl_base.SetLabel(f"Prix série actuel : {_eur(self._p_base)}/pc")
        if any(s.moved for s in self.steps):
            pct = (delta / self._p_base * 100) if self._p_base else 0
            self.lbl_sim.SetLabel(f"→ simulé : {_eur(p_sim)}/pc  ({delta:+.4f} € · {pct:+.1f} %)")
            self.lbl_sim.SetForegroundColour(wx.Colour(30, 130, 50) if delta < 0 else wx.Colour(190, 60, 30))
        else:
            self.lbl_sim.SetLabel("")
        any_moved = any(s.moved for s in self.steps)
        self.btn_apply.Enable(any_moved)
        self.btn_reset.Enable(any_moved)

        k_base = self._factor()
        for step, wdg in zip(self.steps, self._widgets):
            k = 0.0 if step.cost.is_temps_masque else k_base
            cycle_txt = f" · TC {step.cycle:.1f} s" if step.pieces != 1 else ""
            wdg["tc_sim"].SetLabel(f"{step.time:.2f} s ({step.time_pct:+d} %){cycle_txt}")
            wdg["r_sim"].SetLabel(f"{step.rate:.0f} €/h ({step.rate_pct:+d} %)")
            wdg["d_tc"].SetLabel(f"{k * step.rate:.4f}")
            wdg["d_rate"].SetLabel(f"{k * step.time * 10:.4f}")
            sel = self.steps.index(step) == self.selected
            wdg["name"].SetLabel(("▶ " if sel else "  ") + step.label)
            wdg["name"].SetForegroundColour(wx.Colour(30, 90, 160) if sel else wx.BLACK)
            wdg["name"].Refresh()
        self.rows_panel.Layout()
        self.Layout()

        # Décomposition de l'écart : effet temps (Δt × taux actuel) + effet taux (t simulé × Δtaux)
        items = []
        for idx, step in enumerate(self.steps):
            if not step.moved:
                continue
            k = 0.0 if step.cost.is_temps_masque else k_base
            if abs(k * (step.time * step.rate - step.time0 * step.rate0)) < 1e-9:
                continue   # étape bougée sans effet (temps nul, temps masqué…)
            items.append(dict(idx=idx, label=step.label,
                              d_time=k * (step.time - step.time0) * step.rate0,
                              d_rate=k * step.time * (step.rate - step.rate0)))
        items.sort(key=lambda it: it["d_time"] + it["d_rate"])
        explained = sum(it["d_time"] + it["d_rate"] for it in items)
        self.waterfall.set_data(dict(p_base=self._p_base, p_sim=p_sim, items=items,
                                     residual=(p_sim - self._p_base) - explained))

        if self.steps:
            step = self.steps[self.selected]
            k = 0.0 if step.cost.is_temps_masque else k_base
            self.chart.set_data(dict(step=step, k=k, p_base=self._p_base, p_sim=p_sim,
                                     p_other=p_sim - k * step.time * step.rate))
        else:
            self.chart.set_data(None)

    # ------------------------------------------------------------------ événements

    def _select(self, idx):
        if idx != self.selected:
            self.selected = idx
            self._recompute()

    def _on_slider(self, idx):
        step, wdg = self.steps[idx], self._widgets[idx]
        step.time_pct = wdg["s_tc"].GetValue()
        step.rate_pct = wdg["s_rate"].GetValue()
        self.selected = idx
        self._recompute()

    def _reset_sliders(self):
        for step, wdg in zip(self.steps, self._widgets):
            step.time_pct = step.rate_pct = 0
            wdg["s_tc"].SetValue(0)
            wdg["s_rate"].SetValue(0)
        self._recompute()

    def _on_apply(self, event):
        changed = [s for s in self.steps if s.moved]
        if not changed:
            return
        for s in changed:
            if s.time_pct:
                # On enregistre le temps de cycle : temps par pièce × pièces simultanées
                s.cost.serie_cycle_time_s = round(s.cycle, 3)
            if s.rate_pct:
                s.cost.serie_hourly_rate = round(s.rate, 2)
        if callable(self.on_applied):
            self.on_applied()
        self.load(self.project)
