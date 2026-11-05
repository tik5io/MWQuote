# ui/components/trades.py
"""Code couleur par métier.

Le logiciel est un outil de gestion de projet : un même projet est travaillé par
plusieurs métiers (amont projet, méthode, qualité, chiffrage) qui s'alimentent en
permanence. On ne sépare donc pas l'interface par métier : on garde un écran
unique et on « étiquette » chaque information avec la couleur de son métier.

    Projet     violet  contexte, client, plans, dossier réseau
    Méthode    bleu    gamme, opérations, temps
    Qualité    vert    contrôle, commentaires et exports qualité
    Chiffrage  ambre   coûts, outillage, tarif, offres

Ce module ne contient que de la présentation : aucune logique métier.
"""
import math

import wx


def _mix(c: wx.Colour, other: wx.Colour, t: float) -> wx.Colour:
    return wx.Colour(int(c.Red() + (other.Red() - c.Red()) * t),
                     int(c.Green() + (other.Green() - c.Green()) * t),
                     int(c.Blue() + (other.Blue() - c.Blue()) * t))


class Trade:
    """Un métier : nom affiché et couleur (+ déclinaisons pour texte et fonds)."""

    def __init__(self, key: str, label: str, colour: wx.Colour):
        self.key = key
        self.label = label
        self.colour = colour

    @property
    def text(self) -> wx.Colour:
        """Variante foncée, lisible comme texte sur fond blanc."""
        return _mix(self.colour, wx.BLACK, 0.25)

    @property
    def tint(self) -> wx.Colour:
        """Variante très claire, pour un fond de bandeau."""
        return _mix(self.colour, wx.WHITE, 0.9)


PROJET = Trade("projet", "Projet", wx.Colour(124, 58, 237))
METHODE = Trade("methode", "Méthode", wx.Colour(37, 99, 235))
QUALITE = Trade("qualite", "Qualité", wx.Colour(22, 163, 74))
CHIFFRAGE = Trade("chiffrage", "Chiffrage", wx.Colour(217, 119, 6))

TRADES = (PROJET, METHODE, QUALITE, CHIFFRAGE)


def dot_bitmap(colour: wx.Colour, size: int = 12) -> wx.Bitmap:
    """Pastille ronde anticrénelée (RGBA) ; carré plein si la création échoue."""
    try:
        radius = size / 2.0
        buf = bytearray(size * size * 4)
        for y in range(size):
            for x in range(size):
                d = math.hypot(x + 0.5 - radius, y + 0.5 - radius)
                alpha = max(0.0, min(1.0, radius - d + 0.5))
                i = (y * size + x) * 4
                buf[i:i + 4] = bytes((colour.Red(), colour.Green(), colour.Blue(), int(alpha * 255)))
        return wx.Bitmap.FromBufferRGBA(size, size, bytes(buf))
    except Exception:
        bmp = wx.Bitmap(size, size)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(colour))
        dc.Clear()
        dc.SelectObject(wx.NullBitmap)
        return bmp


class TradeImages:
    """ImageList des pastilles métier, pour les onglets (`notebook.SetImageList`)."""

    def __init__(self, size: int = 12):
        self.imagelist = wx.ImageList(size, size)
        self._index = {t.key: self.imagelist.Add(dot_bitmap(t.colour, size)) for t in TRADES}

    def index(self, trade: Trade) -> int:
        return self._index[trade.key]


def stripe(parent, trade: Trade, height: int = 3) -> wx.Panel:
    """Fine bande de couleur en haut d'un bandeau."""
    panel = wx.Panel(parent, size=(-1, height))
    panel.SetMinSize((-1, height))
    panel.SetBackgroundColour(trade.colour)
    return panel


def caption(parent, trade: Trade, text: str) -> wx.StaticText:
    """Intitulé de section : « MÉTHODE · GAMME », dans la couleur du métier."""
    lbl = wx.StaticText(parent, label=f"{trade.label.upper()} · {text.upper()}")
    lbl.SetFont(wx.Font(wx.FontInfo(8).FaceName("Segoe UI").Bold()))
    lbl.SetForegroundColour(trade.text)
    return lbl


def tag(label: wx.StaticText, trade: Trade) -> wx.StaticText:
    """Colore un libellé existant avec la couleur de son métier."""
    label.SetForegroundColour(trade.text)
    return label


def legend(parent, background: wx.Colour = None) -> wx.Panel:
    """Légende compacte : une pastille + le nom de chaque métier."""
    panel = wx.Panel(parent)
    if background is not None:
        panel.SetBackgroundColour(background)
    sizer = wx.BoxSizer(wx.HORIZONTAL)
    for t in TRADES:
        sizer.Add(wx.StaticBitmap(panel, bitmap=dot_bitmap(t.colour, 10)), 0,
                  wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        lbl = wx.StaticText(panel, label=t.label)
        lbl.SetForegroundColour(t.text)
        sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
    panel.SetSizer(sizer)
    panel.SetToolTip("Code couleur des métiers : chaque information porte la couleur de son métier.")
    return panel
