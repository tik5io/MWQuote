# ui/components/serie_analysis_charts.py
"""Visualisations d'analyse pour le chiffrage Décomposé (série).

Deux vues « constructives » qui remplacent la cascade « d'où vient l'écart » :

- PriceDecompositionBar : barre empilée du prix /pièce (où part l'argent ?),
  pensée pour rester visible en permanence (dock haut du panneau).
- CapacityBottleneckChart : capacité annuelle par opération vs volume cible,
  goulot et surcharge mis en évidence (pendant visuel du nb de machines).

Ni l'une ni l'autre ne modifie le modèle : elles ne font qu'afficher.
"""
import wx

from ui.components.serie_sensitivity_panel import _eur


# Palette des postes de coût (ordre d'empilement de la barre de décomposition).
COST_COLOURS = [
    ("MO directe",   wx.Colour(0, 140, 150)),
    ("CAPEX",        wx.Colour(30, 90, 160)),
    ("Tooling",      wx.Colour(130, 80, 170)),
    ("Setup",        wx.Colour(220, 140, 40)),
    ("Contrôle",     wx.Colour(200, 90, 120)),
    ("Matières",     wx.Colour(90, 160, 70)),
    ("Logistique",   wx.Colour(150, 120, 60)),
    ("Marge ciale",  wx.Colour(150, 160, 175)),
]

_OK_GREEN   = wx.Colour(40, 150, 70)
_WARN_AMBER = wx.Colour(220, 150, 40)
_OVER_RED   = wx.Colour(200, 60, 40)


def load_charge_colour(charge: float) -> wx.Colour:
    """Couleur selon le taux de charge d'une opération."""
    if charge > 0.85:
        return _OVER_RED
    if charge > 0.70:
        return _WARN_AMBER
    return _OK_GREEN


class _PaintPanel(wx.Panel):
    """Base : double-buffering + repaint sur EVT_SIZE."""

    def __init__(self, parent, style=wx.BORDER_SIMPLE):
        super().__init__(parent, style=style)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.data = None
        self.Bind(wx.EVT_PAINT, lambda e: self.draw(wx.AutoBufferedPaintDC(self), *self.GetClientSize()))
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))

    def set_data(self, data):
        self.data = data
        self.Refresh()

    def draw(self, dc, w, h):   # pragma: no cover - surchargé
        raise NotImplementedError


class PriceDecompositionBar(_PaintPanel):
    """Barre empilée horizontale du prix de vente /pièce, par poste de coût.

    data = dict(price, price_usd, total_cost,
                segments=[dict(label, value, colour)]).
    Les segments s'empilent sur la largeur ; chaque part est annotée en % et €.
    """

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE)

    def draw(self, dc, w, h):
        dc.SetBackground(wx.Brush(wx.Colour(248, 249, 251)))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        small = wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        tiny  = wx.Font(7, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        big   = wx.Font(17, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        lbl   = wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)

        d = self.data
        # --- Bloc prix (gauche) ---
        gc.SetFont(lbl, wx.Colour(90, 90, 90))
        gc.DrawText("PRIX DE VENTE / PIÈCE", 12, 8)
        price = d["price"] if d else 0.0
        gc.SetFont(big, wx.Colour(30, 90, 160))
        price_txt = f"{price:.2f} €" if price else "—"
        gc.DrawText(price_txt, 12, 22)
        pw, _ = gc.GetTextExtent(price_txt)
        if d and d.get("price_usd"):
            gc.SetFont(small, wx.Colour(180, 90, 0))
            gc.DrawText(f"≈ {d['price_usd']:.2f} USD", 12, 50)
        if d and d.get("total_cost") is not None:
            gc.SetFont(small, wx.Colour(120, 120, 120))
            gc.DrawText(f"coût de revient {d['total_cost']:.2f} €", 14 + pw + 10, 34)

        # --- Barre empilée (droite) ---
        bar_x = 230
        bar_w = w - bar_x - 16
        bar_y, bar_h = 12, 26
        if bar_w < 80 or not d or price <= 0 or not d.get("segments"):
            gc.SetFont(small, wx.Colour(140, 140, 140))
            if bar_w >= 80:
                gc.DrawText("Décomposition du prix indisponible.", bar_x, 24)
            return

        segs = [s for s in d["segments"] if s["value"] > 1e-9]
        total = sum(s["value"] for s in segs) or price
        x = bar_x
        gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 1))
        for s in segs:
            seg_w = s["value"] / total * bar_w
            gc.SetBrush(wx.Brush(s["colour"]))
            gc.DrawRectangle(x, bar_y, max(seg_w, 1), bar_h)
            if seg_w > 34:
                pct = s["value"] / price * 100
                gc.SetFont(tiny, wx.Colour(255, 255, 255))
                tw, th = gc.GetTextExtent(f"{pct:.0f}%")
                gc.DrawText(f"{pct:.0f}%", x + (seg_w - tw) / 2, bar_y + (bar_h - th) / 2)
            x += seg_w

        # --- Légende sous la barre (enroulée) ---
        gc.SetFont(small, wx.Colour(70, 70, 70))
        lx, ly = bar_x, bar_y + bar_h + 8
        for s in segs:
            chip = 10
            label = f"{s['label']} {s['value']:.2f} €"
            tw, th = gc.GetTextExtent(label)
            if lx + chip + 4 + tw > w - 8:
                lx = bar_x
                ly += 16
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(wx.Brush(s["colour"]))
            gc.DrawRectangle(lx, ly + 1, chip, chip)
            gc.DrawText(label, lx + chip + 4, ly - 1)
            lx += chip + 4 + tw + 14


class CapacityBottleneckChart(_PaintPanel):
    """Capacité annuelle par opération (barres) face au volume cible (ligne).

    data = dict(volume, items=[dict(label, cap_an, charge, machines, idx)]).
    Le goulot (charge la plus forte) est marqué ◄ ; couleur selon la charge.
    Un clic sur une barre rappelle on_select(idx) si défini.
    """

    ROW_H = 30

    def __init__(self, parent):
        super().__init__(parent)
        self.on_select = None
        self._hit = []
        self.Bind(wx.EVT_LEFT_DOWN, self._on_click)

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
        small = wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        bold  = wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        self._hit = []

        gc.SetFont(bold, wx.Colour(40, 40, 40))
        gc.DrawText("Capacité annuelle par opération vs volume cible", 10, 6)

        d = self.data
        items = (d or {}).get("items") or []
        if not items:
            gc.SetFont(small, wx.Colour(130, 130, 130))
            gc.DrawText("Aucune opération interne : rien à cadencer.", 10, 30)
            return

        volume = max(d.get("volume", 0), 0)
        caps = [it["cap_an"] for it in items if it["cap_an"] > 0]
        x_max = max(caps + [volume]) * 1.12 if (caps or volume) else 1.0
        if x_max <= 0:
            x_max = 1.0

        bottleneck = max(range(len(items)), key=lambda i: items[i]["charge"])

        label_w = int(min(190, w * 0.30))
        value_w = 120
        ml, mt = label_w, 30
        cw = w - ml - value_w - 16
        if cw < 60:
            return
        row_h = min(self.ROW_H, max(16, (h - mt - 28) // max(len(items), 1)))

        def to_x(v):
            return ml + v / x_max * cw

        # Ligne « volume cible »
        if volume > 0:
            vx = to_x(volume)
            gc.SetPen(wx.Pen(wx.Colour(60, 60, 60), 1, wx.PENSTYLE_LONG_DASH))
            gc.StrokeLine(vx, mt - 4, vx, mt + len(items) * row_h + 2)
            gc.SetFont(small, wx.Colour(60, 60, 60))
            gc.DrawText(f"cible {volume:,.0f}".replace(",", " "), min(vx + 3, w - 90), mt - 16)

        for i, it in enumerate(items):
            y = mt + i * row_h
            bar_y, bar_h = y + 4, row_h - 8
            is_goulot = (i == bottleneck)
            # Libellé opération
            gc.SetFont(bold if is_goulot else small, wx.Colour(30, 30, 30))
            name = ("◄ " if is_goulot else "") + it["label"]
            max_chars = max(10, label_w // 6)
            if len(name) > max_chars:
                name = name[:max_chars - 1] + "…"
            gc.DrawText(name, 6, y + (row_h - 12) / 2)
            # Barre capacité
            colour = load_charge_colour(it["charge"])
            bw = max(to_x(it["cap_an"]) - ml, 1) if it["cap_an"] > 0 else 1
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(wx.Brush(colour))
            gc.DrawRectangle(ml, bar_y, bw, bar_h)
            # Annotation droite : charge % · nb machines (+ TC goulot sur l'opération goulot)
            gc.SetFont(small, colour)
            extra = f"  ·  TC {it['tc']:.1f} s ◄ goulot" if (is_goulot and it.get("tc")) else ""
            gc.DrawText(f"{it['charge']*100:.0f}%  ·  {it['machines']} m.{extra}",
                        ml + cw + 8, y + (row_h - 12) / 2)
            self._hit.append((y, y + row_h, it.get("idx", i)))

        # Légende couleurs
        ly = mt + len(items) * row_h + 8
        gc.SetFont(small, wx.Colour(90, 90, 90))
        legend = [("charge ≤ 70 %", _OK_GREEN), ("70–85 %", _WARN_AMBER), ("> 85 % (surcharge)", _OVER_RED)]
        lx = ml
        for txt, colour in legend:
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(wx.Brush(colour))
            gc.DrawRectangle(lx, ly + 2, 12, 10)
            gc.DrawText(txt, lx + 16, ly)
            tw, _ = gc.GetTextExtent(txt)
            lx += 16 + tw + 16
