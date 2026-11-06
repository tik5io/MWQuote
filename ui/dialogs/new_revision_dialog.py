# ui/dialogs/new_revision_dialog.py
"""Création d'un nouvel indice d'une offre archivée : ajustement des coefficients de vente.

La fenêtre part des coefficients de l'indice sélectionné et rend les nouveaux (`get_coefficients`,
même format que `domain.offers.snapshot_coefficients`). Elle ne modifie pas le projet : c'est
l'appelant qui les applique puis génère l'offre.

  Taux horaire : un coefficient par quantité, modifiable directement ou via le prix pièce visé
                 (les deux champs sont liés : prix = coût de base × coefficient).
  Décomposé    : la marge commerciale globale (%).
"""
import copy

import wx

from domain import offers


class NewRevisionDialog(wx.Dialog):
    def __init__(self, parent, devis_ref, next_revision, base_coeffs, from_revision=None,
                 lot_base_prices=None, serie_price_fn=None, fx=1.0, symbol="€"):
        """
        base_coeffs     coefficients de départ (photo de l'indice sélectionné ou paramètres courants)
        lot_base_prices {quantité: prix pièce à coefficient 1} (Taux horaire), pour lier coefficient et prix
        serie_price_fn  fonction(marge globale 0..1) -> prix série / pièce (Décomposé)
        fx, symbol      conversion et symbole de la devise d'affichage
        """
        super().__init__(parent, title=f"Nouvel indice {next_revision} · offre {devis_ref}",
                         style=wx.DEFAULT_DIALOG_STYLE)
        self._base = copy.deepcopy(base_coeffs)
        self._fx = fx or 1.0
        self._symbol = symbol
        self._lot_base = lot_base_prices or {}
        self._serie_price_fn = serie_price_fn
        self._busy = False           # évite les rebonds coefficient ↔ prix
        self._rows = []              # [(quantité, spin coefficient, spin prix, label écart)]

        root = wx.BoxSizer(wx.VERTICAL)
        origin = f" (départ : indice {from_revision})" if from_revision else ""
        intro = wx.StaticText(
            self, label=f"Ajustez les coefficients de vente de l'offre {devis_ref}{origin}.\n"
                        f"L'offre sera ensuite générée sous l'indice {next_revision} ; "
                        "les indices précédents restent tels qu'émis.")
        root.Add(intro, 0, wx.ALL, 12)

        if self._base.get("mode") == "serie":
            root.Add(self._build_serie(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        else:
            root.Add(self._build_lot(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        self.hint = wx.StaticText(self, label="")
        self.hint.SetForegroundColour(wx.Colour(100, 116, 139))
        root.Add(self.hint, 0, wx.ALL, 12)

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.ok_btn = self.FindWindowById(wx.ID_OK)
        self.ok_btn.SetLabel("Générer l'offre…")
        root.Add(btns, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(root)
        self._update_state()

    # ------------------------------------------------------------------ Taux horaire

    def _build_lot(self):
        grid = wx.FlexGridSizer(cols=4, hgap=14, vgap=8)
        for text in ("Quantité", "Coefficient", f"Prix ({self._symbol}/pièce)", "Écart"):
            lbl = wx.StaticText(self, label=text)
            lbl.SetFont(lbl.GetFont().Bold())
            grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        quantities = [int(q) for q in self._base.get("quantities", [])]
        rates = self._base.get("rates") or {}
        for q in quantities:
            rate = float(rates.get(str(q), 1.0))
            base_price = self._lot_base.get(q, 0.0)
            coef = wx.SpinCtrlDouble(self, min=0.0, max=100.0, inc=0.01, initial=rate, size=(100, -1))
            coef.SetDigits(4)
            price = wx.SpinCtrlDouble(self, min=0.0, max=10_000_000.0, inc=0.05,
                                      initial=base_price * rate * self._fx, size=(110, -1))
            price.SetDigits(2)
            price.Enable(base_price > 0)             # sans coût de base, seul le coefficient est réglable
            gap = wx.StaticText(self, label="", size=(70, -1))
            coef.Bind(wx.EVT_SPINCTRLDOUBLE, lambda e, i=len(self._rows): self._on_coef(i))
            coef.Bind(wx.EVT_TEXT, lambda e, i=len(self._rows): self._on_coef(i))
            price.Bind(wx.EVT_SPINCTRLDOUBLE, lambda e, i=len(self._rows): self._on_price(i))
            price.Bind(wx.EVT_TEXT, lambda e, i=len(self._rows): self._on_price(i))
            grid.Add(wx.StaticText(self, label=f"{q}"), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(coef, 0)
            grid.Add(price, 0)
            grid.Add(gap, 0, wx.ALIGN_CENTER_VERTICAL)
            self._rows.append((q, coef, price, gap, rate))
        return grid

    def _on_coef(self, i):
        if self._busy:
            return
        q, coef, price, _gap, _orig = self._rows[i]
        base = self._lot_base.get(q, 0.0)
        if base > 0:
            self._busy = True
            try:
                price.SetValue(base * coef.GetValue() * self._fx)
            finally:
                self._busy = False
        self._update_state()

    def _on_price(self, i):
        if self._busy:
            return
        q, coef, price, _gap, _orig = self._rows[i]
        base = self._lot_base.get(q, 0.0)
        if base > 0:
            self._busy = True
            try:
                coef.SetValue(price.GetValue() / self._fx / base)
            finally:
                self._busy = False
        self._update_state()

    # ------------------------------------------------------------------ Décomposé

    def _build_serie(self):
        box = wx.FlexGridSizer(cols=2, hgap=14, vgap=8)
        box.Add(wx.StaticText(self, label="Marge commerciale globale (%) :"), 0, wx.ALIGN_CENTER_VERTICAL)
        margin = float(self._base.get("global_commercial_margin", 0.0)) * 100.0
        self.margin = wx.SpinCtrlDouble(self, min=0.0, max=100.0, inc=0.5, initial=margin, size=(100, -1))
        self.margin.SetDigits(1)
        self.margin.Bind(wx.EVT_SPINCTRLDOUBLE, lambda e: self._update_state())
        self.margin.Bind(wx.EVT_TEXT, lambda e: self._update_state())
        box.Add(self.margin, 0)
        box.Add(wx.StaticText(self, label=f"Prix série ({self._symbol}/pièce) :"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.serie_price = wx.StaticText(self, label="—")
        self.serie_price.SetFont(self.serie_price.GetFont().Bold())
        box.Add(self.serie_price, 0, wx.ALIGN_CENTER_VERTICAL)
        return box

    # ------------------------------------------------------------------ état

    def get_coefficients(self) -> dict:
        """Nouveaux coefficients, au format des photos d'indice."""
        new = copy.deepcopy(self._base)
        if new.get("mode") == "serie":
            new["global_commercial_margin"] = self.margin.GetValue() / 100.0
        else:
            new["rates"] = {str(q): float(coef.GetValue()) for q, coef, _p, _g, _o in self._rows}
        return new

    def _update_state(self):
        """Écarts, prix série, et bouton actif seulement si quelque chose a changé."""
        new = self.get_coefficients()
        if self._base.get("mode") == "serie":
            if self._serie_price_fn:
                price = self._serie_price_fn(new["global_commercial_margin"]) * self._fx
                self.serie_price.SetLabel(f"{price:,.2f} {self._symbol}".replace(",", " "))
        else:
            for q, coef, _price, gap, orig in self._rows:
                if orig:
                    pct = (coef.GetValue() / orig - 1.0) * 100.0
                    gap.SetLabel(f"{pct:+.1f} %" if abs(pct) >= 0.05 else "")
                else:
                    gap.SetLabel("")
        changed = not offers.same_coefficients(self._base, new)
        self.ok_btn.Enable(changed)
        self.hint.SetLabel("" if changed else "Modifiez au moins un coefficient pour créer un nouvel indice.")
        self.Layout()
