# ui/components/line_icons.py
"""Icônes vectorielles « au trait » (style outline, monochromes) pour les boutons.

Chaque icône est dessinée dans une boîte de 24 × 24 puis mise à l'échelle : même
épaisseur de trait, mêmes angles arrondis, quelle que soit la taille. Elles
remplacent les émojis (rendu variable selon le poste, couleurs imposées).
"""
import math

import wx

# émoji historiquement passés aux boutons → nom d'icône
EMOJI_TO_ICON = {
    "➕": "plus", "🗑": "trash", "⚙": "gear", "🛠": "wrench", "🧾": "document",
    "👁": "eye", "💾": "save", "🔁": "refresh", "📎": "pdf",
}


def _path(gc):
    return gc.CreatePath()


def _plus(gc, p):
    p.MoveToPoint(12, 5); p.AddLineToPoint(12, 19)
    p.MoveToPoint(5, 12); p.AddLineToPoint(19, 12)


def _trash(gc, p):
    p.MoveToPoint(4.5, 7); p.AddLineToPoint(19.5, 7)                       # couvercle
    p.MoveToPoint(9.5, 7); p.AddLineToPoint(9.5, 4.5); p.AddLineToPoint(14.5, 4.5); p.AddLineToPoint(14.5, 7)
    p.MoveToPoint(6.5, 7); p.AddLineToPoint(7.5, 19.5); p.AddLineToPoint(16.5, 19.5); p.AddLineToPoint(17.5, 7)
    p.MoveToPoint(10.2, 10.5); p.AddLineToPoint(10.2, 16)
    p.MoveToPoint(13.8, 10.5); p.AddLineToPoint(13.8, 16)


def _gear(gc, p):
    p.AddCircle(12, 12, 3.2)
    p.AddCircle(12, 12, 6.6)
    for k in range(8):                                                      # dents
        a = k * math.pi / 4
        p.MoveToPoint(12 + 6.6 * math.cos(a), 12 + 6.6 * math.sin(a))
        p.AddLineToPoint(12 + 9.2 * math.cos(a), 12 + 9.2 * math.sin(a))


def _wrench(gc, p):
    """Clé à molette : tête ouverte en haut à droite, manche en diagonale."""
    cx, cy, r = 16.2, 7.8, 3.9
    p.AddArc(cx, cy, r, math.radians(-12), math.radians(282), True)          # tête (mâchoire ouverte vers le haut-droit)
    # manche : deux bords parallèles depuis la tête jusqu'au coin bas-gauche, fermé par un bout arrondi
    dx, dy = -0.7071, 0.7071
    nx, ny = 0.7071, 0.7071
    start = (cx - 2.6, cy + 2.6)
    end = (5.2, 18.8)
    w = 1.45
    p.MoveToPoint(start[0] + nx * w, start[1] + ny * w)
    p.AddLineToPoint(end[0] + nx * w, end[1] + ny * w)
    p.AddLineToPoint(end[0] - nx * w, end[1] - ny * w)
    p.AddLineToPoint(start[0] - nx * w, start[1] - ny * w)


def _document(gc, p):
    p.AddRoundedRectangle(6, 3, 12, 18, 2)
    p.MoveToPoint(9, 8.5); p.AddLineToPoint(15, 8.5)
    p.MoveToPoint(9, 12); p.AddLineToPoint(15, 12)
    p.MoveToPoint(9, 15.5); p.AddLineToPoint(13, 15.5)


def _eye(gc, p):
    p.MoveToPoint(2, 12)
    p.AddCurveToPoint(6, 5.5, 18, 5.5, 22, 12)
    p.AddCurveToPoint(18, 18.5, 6, 18.5, 2, 12)
    p.AddCircle(12, 12, 3)


def _save(gc, p):
    p.MoveToPoint(5, 4); p.AddLineToPoint(16.5, 4); p.AddLineToPoint(20, 7.5)
    p.AddLineToPoint(20, 19); p.AddLineToPoint(5, 19); p.CloseSubpath()
    p.AddRectangle(8, 4, 7, 4.5)
    p.AddRectangle(8, 12.5, 8, 6.5)


def _refresh(gc, p):
    p.AddArc(12, 12, 7, math.radians(-40), math.radians(250), True)
    end = math.radians(250)
    ex, ey = 12 + 7 * math.cos(end), 12 + 7 * math.sin(end)
    p.MoveToPoint(ex - 4, ey - 1.2); p.AddLineToPoint(ex, ey); p.AddLineToPoint(ex + 0.5, ey - 4.5)


def _pdf(gc, p):
    p.MoveToPoint(6, 3); p.AddLineToPoint(14, 3); p.AddLineToPoint(18, 7)
    p.AddLineToPoint(18, 21); p.AddLineToPoint(6, 21); p.CloseSubpath()
    p.MoveToPoint(14, 3); p.AddLineToPoint(14, 7); p.AddLineToPoint(18, 7)


_ICONS = {
    "plus": _plus, "trash": _trash, "gear": _gear, "wrench": _wrench, "document": _document,
    "eye": _eye, "save": _save, "refresh": _refresh, "pdf": _pdf,
}


def has_icon(name: str) -> bool:
    return EMOJI_TO_ICON.get(name, name) in _ICONS


def draw_icon(gc, name: str, x: float, y: float, size: float, colour: wx.Colour) -> bool:
    """Dessine l'icône `name` (ou l'équivalent d'un émoji) dans le carré (x, y, size). False si inconnue."""
    key = EMOJI_TO_ICON.get(name, name)
    builder = _ICONS.get(key)
    if builder is None:
        return False
    scale = size / 24.0
    gc.PushState()
    gc.Translate(x, y)
    gc.Scale(scale, scale)
    pen = gc.CreatePen(wx.GraphicsPenInfo(colour).Width(1.7).Cap(wx.CAP_ROUND).Join(wx.JOIN_ROUND))
    gc.SetPen(pen)
    gc.SetBrush(wx.TRANSPARENT_BRUSH)
    path = gc.CreatePath()
    builder(gc, path)
    gc.StrokePath(path)
    if key == "pdf":                                                         # mention « PDF » dans la page
        font = wx.Font(wx.FontInfo(5).FaceName("Segoe UI").Bold())
        gc.SetFont(font, colour)
        tw, th = gc.GetTextExtent("PDF")[:2]
        gc.DrawText("PDF", 12 - tw / 2, 14.2 - th / 2)
    gc.PopState()
    return True
