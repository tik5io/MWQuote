# ui/components/status_pills.py
"""Bulles de statut : une rangée de pastilles colorées (texte blanc sur fond de couleur).

Utilisée sous la barre des scénarios pour afficher d'un coup d'œil le mode de calcul, le statut
prototype, le secteur et l'état de l'offre du scénario sélectionné. Les pastilles passent à la
ligne quand la place manque ; chacune peut porter une infobulle.
"""
import wx

PILL_PAD_X = 10
PILL_PAD_Y = 3
PILL_GAP = 6
ROW_GAP = 5


class StatusPills(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        self._tags = []                 # [(texte, couleur, infobulle)]
        self._boxes = []                # [(x, y, w, h, texte, couleur, infobulle)] positions calculées
        self._tip = None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._font = wx.Font(wx.FontInfo(9).FaceName("Segoe UI").Bold())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.SetMinSize((-1, self._row_height() + 2 * ROW_GAP))

    def set_tags(self, tags):
        """tags : [(texte, couleur wx.Colour, infobulle optionnelle)], dans l'ordre d'affichage."""
        self._tags = [(t[0], t[1], t[2] if len(t) > 2 else "") for t in tags]
        self._relayout()
        self.Refresh()

    @property
    def tags(self):
        return list(self._tags)

    # ------------------------------------------------------------------ mise en page

    def _row_height(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self._font)
        return dc.GetTextExtent("Ag")[1] + 2 * PILL_PAD_Y

    def _relayout(self):
        """Positionne les pastilles (retour à la ligne) et ajuste la hauteur du panneau."""
        dc = wx.ClientDC(self)
        dc.SetFont(self._font)
        row_h = dc.GetTextExtent("Ag")[1] + 2 * PILL_PAD_Y
        width = max(self.GetClientSize().width, 120)
        x, y = 0, ROW_GAP
        boxes = []
        for text, colour, tip in self._tags:
            w = dc.GetTextExtent(text)[0] + 2 * PILL_PAD_X
            if x > 0 and x + w > width:
                x, y = 0, y + row_h + ROW_GAP
            boxes.append((x, y, w, row_h, text, colour, tip))
            x += w + PILL_GAP
        self._boxes = boxes
        needed = y + row_h + ROW_GAP
        if self.GetMinSize().height != needed:
            self.SetMinSize((-1, needed))
            parent = self.GetParent()
            if parent:
                parent.Layout()

    def _on_size(self, event):
        event.Skip()
        wx.CallAfter(self._safe_relayout)

    def _safe_relayout(self):
        try:
            self._relayout()
            self.Refresh()
        except RuntimeError:
            pass        # panneau détruit entre-temps

    # ------------------------------------------------------------------ dessin et infobulles

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        gc.SetFont(self._font, wx.WHITE)
        for x, y, w, h, text, colour, _tip in self._boxes:
            gc.SetBrush(wx.Brush(colour))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawRoundedRectangle(x + 0.5, y + 0.5, w, h, h / 2)          # bulle : extrémités arrondies
            tw, th = gc.GetTextExtent(text)[:2]
            gc.DrawText(text, x + (w - tw) / 2, y + (h - th) / 2)

    def _on_motion(self, event):
        tip = ""
        for x, y, w, h, _text, _colour, tooltip in self._boxes:
            if x <= event.GetX() <= x + w and y <= event.GetY() <= y + h:
                tip = tooltip
                break
        if tip != self._tip:
            self._tip = tip
            self.SetToolTip(tip if tip else None)
        event.Skip()
