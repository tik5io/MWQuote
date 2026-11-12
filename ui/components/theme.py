"""Charte graphique commune (bandeau bleu nuit, boutons plats) des fenêtres MWQuote."""
import wx


# --------------------------------------------------------------------------- #
# Palette et widgets communs                                         #
# --------------------------------------------------------------------------- #
UI_NAVY = wx.Colour(22, 34, 56)
UI_NAVY_MUTED = wx.Colour(148, 163, 184)
UI_ACCENT = wx.Colour(37, 99, 235)
UI_ACCENT_HOVER = wx.Colour(29, 78, 216)
UI_BG = wx.Colour(244, 246, 250)
UI_BORDER = wx.Colour(222, 227, 235)
UI_TEXT = wx.Colour(30, 41, 59)
UI_MUTED = wx.Colour(100, 116, 139)
UI_ROW_ALT = wx.Colour(247, 249, 252)
UI_ROW_SERIE = wx.Colour(236, 248, 241)
UI_ROW_PROTO = wx.Colour(255, 246, 232)


def font(size, bold=False):
    return wx.Font(size, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL,
                   wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL, faceName="Segoe UI")


class FlatButton(wx.Control):
    """Bouton plat à coins arrondis (primaire / secondaire / pastille de filtre)."""

    def __init__(self, parent, label, kind="secondary"):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._label = label
        self._kind = kind
        self._active = False
        self._hover = False
        self._down = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetFont(font(10, bold=(kind == "primary")))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_LEFT_DOWN, self._on_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_down)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.InvalidateBestSize()

    # -- API --
    def SetLabel(self, label):
        self._label = label
        self.InvalidateBestSize()
        self.Refresh()
        if self.GetContainingSizer():
            self.GetContainingSizer().Layout()

    def GetLabel(self):
        return self._label

    def SetActive(self, active):
        self._active = bool(active)
        self.Refresh()

    def Enable(self, enable=True):
        result = super().Enable(enable)
        self.Refresh()
        return result

    def Disable(self):
        return self.Enable(False)

    def AcceptsFocus(self):
        return False

    # -- internes --
    def DoGetBestSize(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        w, h = dc.GetTextExtent(self._label)
        pad_x = 14 if self._kind == "chip" else 18
        return wx.Size(w + 2 * pad_x, 32 if self._kind != "chip" else 28)

    def _set_hover(self, value):
        self._hover = value
        if not value:
            self._down = False
        self.Refresh()

    def _on_down(self, event):
        if self.IsEnabled():
            self._down = True
            self.CaptureMouse() if not self.HasCapture() else None
            self.Refresh()

    def _on_up(self, event):
        if self.HasCapture():
            self.ReleaseMouse()
        was_down = self._down
        self._down = False
        self.Refresh()
        if was_down and self.IsEnabled() and self.GetClientRect().Contains(event.GetPosition()):
            evt = wx.CommandEvent(wx.wxEVT_BUTTON, self.GetId())
            evt.SetEventObject(self)
            self.GetEventHandler().ProcessEvent(evt)

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        parent_bg = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent_bg))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        w, h = self.GetClientSize()
        enabled = self.IsEnabled()

        if self._kind == "primary":
            fill = UI_ACCENT_HOVER if (self._hover or self._down) else UI_ACCENT
            border, text = fill, wx.WHITE
        elif self._kind == "chip":
            if self._active:
                fill, border, text = UI_NAVY, UI_NAVY, wx.WHITE
            else:
                fill = wx.Colour(232, 237, 245) if self._hover else wx.WHITE
                border, text = UI_BORDER, UI_TEXT
        else:
            fill = wx.Colour(236, 241, 249) if (self._hover and enabled) else wx.WHITE
            border, text = UI_BORDER, UI_TEXT
        if not enabled:
            fill, border, text = wx.Colour(240, 242, 246), UI_BORDER, wx.Colour(160, 170, 185)

        radius = h / 2 if self._kind == "chip" else 6
        gc.SetBrush(wx.Brush(fill))
        gc.SetPen(wx.Pen(border, 1))
        gc.DrawRoundedRectangle(0.5, 0.5, w - 1, h - 1, radius)

        gc.SetFont(self.GetFont(), text)
        tw, th = gc.GetTextExtent(self._label)[:2]
        gc.DrawText(self._label, (w - tw) / 2, (h - th) / 2)





def build_header(parent, title, subtitle=""):
    """Bandeau bleu nuit : retourne (panel, sizer, title_lbl, subtitle_lbl).

    L'appelant ajoute ses indicateurs / boutons au sizer (horizontal) ; le bloc titre est déjà posé,
    suivi d'un espaceur extensible.
    """
    header = wx.Panel(parent)
    header.SetBackgroundColour(UI_NAVY)
    h = wx.BoxSizer(wx.HORIZONTAL)
    titles = wx.BoxSizer(wx.VERTICAL)
    title_lbl = wx.StaticText(header, label=title, style=wx.ST_ELLIPSIZE_END)
    title_lbl.SetFont(font(18, bold=True))
    title_lbl.SetForegroundColour(wx.WHITE)
    sub_lbl = wx.StaticText(header, label=subtitle, style=wx.ST_ELLIPSIZE_END)
    sub_lbl.SetFont(font(9))
    sub_lbl.SetForegroundColour(UI_NAVY_MUTED)
    titles.Add(title_lbl, 0, wx.EXPAND)
    titles.Add(sub_lbl, 0, wx.EXPAND | wx.TOP, 1)
    h.Add(titles, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.TOP | wx.BOTTOM, 20)
    header.SetSizer(h)
    return header, h, title_lbl, sub_lbl


class ScenarioTab(wx.Control):
    """Carte de scénario : titre (S1 + nom) et détail sur deux lignes ; pleine couleur quand elle est active.

    Émet wxEVT_TOGGLEBUTTON au clic (comme l'ancien ToggleButton) ; double-clic et clic droit restent
    des événements souris ordinaires que l'appelant peut lier.
    """

    def __init__(self, parent, title, detail, selected=False, locked=False):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._title, self._detail = title, detail
        self._selected, self._locked = bool(selected), bool(locked)
        self._hover = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._font_title = font(10, bold=True)
        self._font_detail = font(8)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_LEFT_UP, self._on_up)
        self.InvalidateBestSize()

    def SetValue(self, selected):
        self._selected = bool(selected)
        self.Refresh()

    def GetValue(self):
        return self._selected

    def AcceptsFocus(self):
        return False

    def _title_text(self):
        return self._title

    def DoGetBestSize(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self._font_title)
        w1 = dc.GetTextExtent(self._title_text())[0]
        dc.SetFont(self._font_detail)
        w2 = dc.GetTextExtent(self._detail)[0]
        return wx.Size(max(w1 + (20 if self._locked else 0), w2) + 28, 46)

    def _set_hover(self, value):
        self._hover = value
        self.Refresh()

    def _on_up(self, event):
        if self.GetClientRect().Contains(event.GetPosition()):
            evt = wx.CommandEvent(wx.wxEVT_TOGGLEBUTTON, self.GetId())
            evt.SetEventObject(self)
            evt.SetInt(1)
            wx.CallAfter(self._emit, evt)       # la barre est reconstruite par le gestionnaire : hors de notre événement souris
        event.Skip()

    def _emit(self, evt):
        try:
            self.GetEventHandler().ProcessEvent(evt)
        except RuntimeError:
            pass

    @staticmethod
    def _draw_lock(gc, x, y, colour):
        """Petit cadenas vectoriel (les emojis ne s'affichent pas dans le dessin graphique)."""
        import math
        gc.SetPen(wx.Pen(colour, 2))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        shackle = gc.CreatePath()
        shackle.AddArc(x + 5, y + 4, 3.2, math.pi, 2 * math.pi, True)
        shackle.MoveToPoint(x + 1.8, y + 4)
        shackle.AddLineToPoint(x + 1.8, y + 7)
        shackle.MoveToPoint(x + 8.2, y + 4)
        shackle.AddLineToPoint(x + 8.2, y + 7)
        gc.StrokePath(shackle)
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(colour))
        gc.DrawRoundedRectangle(x, y + 7, 10, 7.5, 1.8)

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        w, h = self.GetClientSize()
        if self._selected:
            fill, border, t1, t2 = UI_ACCENT, UI_ACCENT, wx.WHITE, wx.Colour(219, 234, 254)
        else:
            fill = wx.Colour(236, 241, 249) if self._hover else wx.WHITE
            border = UI_ACCENT if self._hover else UI_BORDER
            t1, t2 = UI_TEXT, UI_MUTED
        gc.SetBrush(wx.Brush(fill))
        gc.SetPen(wx.Pen(border, 1))
        gc.DrawRoundedRectangle(0.5, 0.5, w - 1, h - 1, 8)
        gc.SetFont(self._font_title, t1)
        gc.DrawText(self._title_text(), 14, 6)
        if self._locked:
            tw = gc.GetTextExtent(self._title_text())[0]
            self._draw_lock(gc, 14 + tw + 8, 8, t1)
        gc.SetFont(self._font_detail, t2)
        gc.DrawText(self._detail, 14, 26)
