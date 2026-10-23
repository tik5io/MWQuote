# ui/components/ribbon_button.py
import wx

from ui.components.line_icons import draw_icon, has_icon

ACCENT = wx.Colour(37, 99, 235)       # bleu action
DANGER = wx.Colour(220, 38, 38)       # rouge suppression
TOOLING = wx.Colour(217, 119, 6)      # ambre outillage
SURFACE = wx.Colour(248, 250, 252)    # fond de bandeau
BORDER = wx.Colour(226, 232, 240)


def _mix(c: wx.Colour, other: wx.Colour, t: float) -> wx.Colour:
    return wx.Colour(int(c.Red() + (other.Red() - c.Red()) * t),
                     int(c.Green() + (other.Green() - c.Green()) * t),
                     int(c.Blue() + (other.Blue() - c.Blue()) * t))


class RibbonButton(wx.Control):
    """Bouton « carte » moderne : pastille d'icône, titre, sous-titre optionnel.

    Émet un wx.EVT_BUTTON classique (Bind(wx.EVT_BUTTON, handler) fonctionne).
    big=True : format ruban (icône au-dessus du texte) ; sinon format compact
    horizontal (icône à gauche) pour les ajouts d'éléments enfants.
    """

    def __init__(self, parent, icon: str, label: str, subtitle: str = "",
                 accent: wx.Colour = ACCENT, big: bool = False, size=wx.DefaultSize):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._icon, self._label, self._subtitle = icon, label, subtitle
        self._accent, self._big = accent, big
        self._hover = self._down = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        default = wx.Size(120, 78) if big else wx.Size(220, 52)
        self.SetInitialSize(wx.Size(size[0] if size[0] > 0 else default.x,
                                    size[1] if size[1] > 0 else default.y))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set(hover=True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set(hover=False, down=False))
        self.Bind(wx.EVT_LEFT_DOWN, lambda e: self._set(down=True))
        self.Bind(wx.EVT_LEFT_UP, self._on_up)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def AcceptsFocus(self):
        return True

    def _set(self, hover=None, down=None):
        if hover is not None:
            self._hover = hover
        if down is not None:
            self._down = down
        self.Refresh()

    def _fire(self):
        if self.IsEnabled():
            wx.PostEvent(self, wx.CommandEvent(wx.EVT_BUTTON.typeId, self.GetId()))

    def _on_up(self, event):
        was_down = self._down
        self._set(down=False)
        if was_down and self._hover:
            self._fire()

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_SPACE):
            self._fire()
        else:
            event.Skip()

    def set_label(self, label: str, subtitle: str = None):
        self._label = label
        if subtitle is not None:
            self._subtitle = subtitle
        self.Refresh()

    def Enable(self, enable=True):
        res = super().Enable(enable)
        self.Refresh()
        return res

    # ------------------------------------------------------------------ rendu

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        w, h = self.GetClientSize()
        enabled = self.IsEnabled()
        accent = self._accent if enabled else wx.Colour(160, 160, 160)

        fill = wx.WHITE
        if enabled and self._down:
            fill = _mix(accent, wx.WHITE, 0.82)
        elif enabled and self._hover:
            fill = _mix(accent, wx.WHITE, 0.92)
        border = accent if (enabled and self._hover) else BORDER
        gc.SetBrush(wx.Brush(fill))
        gc.SetPen(wx.Pen(border, 1))
        gc.DrawRoundedRectangle(0.5, 0.5, w - 1, h - 1, 10)

        icon_font = wx.Font(wx.FontInfo(20 if self._big else 15).FaceName("Segoe UI Emoji"))
        title_font = wx.Font(wx.FontInfo(10 if self._big else 10).FaceName("Segoe UI").Bold())
        sub_font = wx.Font(wx.FontInfo(8).FaceName("Segoe UI"))
        text_col = wx.Colour(30, 41, 59) if enabled else wx.Colour(160, 160, 160)
        sub_col = wx.Colour(100, 116, 139) if enabled else wx.Colour(180, 180, 180)

        vector = has_icon(self._icon)
        if self._big:
            if vector:
                ih = 28
                draw_icon(gc, self._icon, (w - ih) / 2, 7, ih, accent)
            else:
                gc.SetFont(icon_font, accent)
                iw, ih = gc.GetTextExtent(self._icon)[:2]
                gc.DrawText(self._icon, (w - iw) / 2, 6)
            gc.SetFont(title_font, text_col)
            tw, th = gc.GetTextExtent(self._label)[:2]
            gc.DrawText(self._label, (w - tw) / 2, 6 + ih + 4)
        else:
            # pastille d'icône
            pad = 8
            badge = h - 2 * pad
            gc.SetBrush(wx.Brush(_mix(accent, wx.WHITE, 0.85)))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawRoundedRectangle(pad, pad, badge, badge, 8)
            if vector:
                glyph = badge * 0.62
                draw_icon(gc, self._icon, pad + (badge - glyph) / 2, pad + (badge - glyph) / 2, glyph, accent)
            else:
                gc.SetFont(icon_font, accent)
                iw, ih = gc.GetTextExtent(self._icon)[:2]
                gc.DrawText(self._icon, pad + (badge - iw) / 2, pad + (badge - ih) / 2)
            x = pad + badge + 10
            gc.SetFont(title_font, text_col)
            tw, th = gc.GetTextExtent(self._label)[:2]
            if self._subtitle:
                gc.DrawText(self._label, x, pad - 1)
                gc.SetFont(sub_font, sub_col)
                gc.DrawText(self._subtitle, x, pad - 1 + th + 1)
            else:
                gc.DrawText(self._label, x, (h - th) / 2)
