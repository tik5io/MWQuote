# ui/dialogs/phase_dialog.py
import wx

from domain.client import PROTOTYPE_LABEL, SECTORS, SECTOR_NORMS, normalize_sectors
from domain.phase import Phase, PhaseKind, ToolingBilling, default_tooling_billing

DEFAULT_QUANTITIES = [1, 10, 50, 100]
DEFAULT_ANNUAL_VOLUME = 100000


class PhaseDialog(wx.Dialog):
    """Création / édition d'une phase.

    Une phase = une typologie de calcul + sa quantité :
      - « Taux horaire » (ex-Lot) : une PLAGE de quantités commandées (temps × taux) ;
        l'outillage y est toujours refacturé séparément (jamais amorti).
      - « Décomposé » (ex-Série) : un VOLUME annuel unique (coûts décomposés) ;
        l'outillage peut y être amorti.

    Saisie rapide des quantités (Taux horaire) : taper une valeur puis Entrée,
    répété pour chaque déclinaison de taille de lot (valeur ENTER valeur ENTER…).

    Une version = la gamme + cette configuration : pour vendre la même gamme
    autrement (autres quantités, autre mode de calcul) on crée une NOUVELLE
    version ; le type de calcul d'une version existante n'est donc pas modifiable.

    bases    : [(indice, libellé)] des versions Taux horaire proposables comme point de
               départ d'une version Décomposé (sa gamme et ses temps sont copiés à la
               création, puis le lien est rompu)
    phase    : configuration à modifier (mode édition)
    template : configuration servant de valeurs initiales à une nouvelle version
    label    : nom de la version (peut rester vide : « V2 »…)
    prototype: statut prototype du scénario (propre à chaque scénario, pas au projet)
    sectors  : normes suivies par le scénario (ISO 13485 = Médical, ISO 9100 = Aéronautique,
               cumulables ; aucune = Autre)
    offer_comments : génère les commentaires d'offre (mentions de traçabilité et prototype)

    ShowModal() renvoie wx.ID_OK ou wx.ID_CANCEL.
    """

    def __init__(self, parent, phase: Phase = None, title: str = None, label: str = None,
                 template: Phase = None, bases: list = None, default_base: int = None,
                 prototype: bool = False, sectors=None, offer_comments: bool = True):
        title = title or ("Modifier le scénario" if phase else "Nouveau scénario")
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE)
        self._editing = phase is not None
        source = phase or template
        phase = source  # valeurs initiales (édition ou préremplissage)

        self._sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=10)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label="Nom (optionnel) :"), 0, wx.ALIGN_CENTER_VERTICAL)
        initial_label = label if label is not None else ""
        self.label_ctrl = wx.TextCtrl(self, value=initial_label, size=(220, -1))
        grid.Add(self.label_ctrl, 1, wx.EXPAND)

        # Statut prototype : propre au scénario (un même projet peut avoir un scénario prototype
        # et un scénario série) ; ajoute les mentions « pièce prototype » aux offres de ce scénario
        grid.Add(wx.StaticText(self, label=""), 0)
        self.prototype_chk = wx.CheckBox(self, label="Prototype")
        self.prototype_chk.SetValue(bool(prototype))
        self.prototype_chk.SetToolTip(PROTOTYPE_LABEL)
        grid.Add(self.prototype_chk, 0, wx.ALIGN_CENTER_VERTICAL)

        # Normes suivies par le scénario : ISO 13485 (médical) et/ou ISO 9100 (aéronautique), cumulables,
        # aucune = Autre. L'offre le dit explicitement pour chacune : « Applicable » si cochée,
        # « Non applicable » sinon.
        grid.Add(wx.StaticText(self, label="Normes suivies :"), 0, wx.ALIGN_CENTER_VERTICAL)
        sector_row = wx.BoxSizer(wx.HORIZONTAL)
        self.sector_chks = {}
        chosen = set(normalize_sectors(sectors))
        for sector in SECTORS:
            norm = SECTOR_NORMS[sector]
            chk = wx.CheckBox(self, label=norm)
            chk.SetValue(sector in chosen)
            chk.SetToolTip(f"Cochée : l'offre indique « Traçabilité et suivi {norm} Applicable ».\n"
                           f"Non cochée : l'offre indique « Traçabilité et suivi {norm} Non applicable ».")
            sector_row.Add(chk, 0, wx.RIGHT, 12)
            self.sector_chks[sector] = chk
        other = wx.StaticText(self, label="(aucune = Autre)")
        other.SetForegroundColour(wx.Colour(110, 110, 110))
        sector_row.Add(other, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(sector_row, 0, wx.ALIGN_CENTER_VERTICAL)

        grid.Add(wx.StaticText(self, label=""), 0)
        self.comments_chk = wx.CheckBox(self, label="Générer les commentaires d'offre")
        self.comments_chk.SetValue(bool(offer_comments))
        self.comments_chk.SetToolTip(
            "Coché : les offres de ce scénario reçoivent automatiquement, pour chaque norme, la mention "
            "« Applicable » ou « Non applicable » (selon les normes suivies) et, pour un prototype, les "
            "mentions prototype.\n"
            "Décoché : seuls les commentaires saisis dans la gamme figurent sur l'offre.")
        grid.Add(self.comments_chk, 0, wx.ALIGN_CENTER_VERTICAL)

        grid.Add(wx.StaticText(self, label="Type de calcul :"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.kind_ctrl = wx.Choice(self, choices=[
            "Taux horaire (quantités commandées)",
            "Décomposé (coûts série)",
        ])
        self.kind_ctrl.SetSelection(1 if phase and phase.kind == PhaseKind.SERIE else 0)
        self.kind_ctrl.Enable(not self._editing)
        self.kind_ctrl.Bind(wx.EVT_CHOICE, self._on_kind_changed)
        grid.Add(self.kind_ctrl, 1, wx.EXPAND)

        # Scénario Taux horaire dont on reprend la gamme et les temps (Décomposé uniquement)
        self._bases = list(bases or [])
        self.base_label = wx.StaticText(self, label="Scénario Taux horaire de départ :")
        grid.Add(self.base_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.base_ctrl = wx.Choice(self, choices=[name for _, name in self._bases])
        if self._bases:
            ids = [i for i, _ in self._bases]
            self.base_ctrl.SetSelection(ids.index(default_base) if default_base in ids else 0)
        self.base_ctrl.SetToolTip(
            "La structure (étapes) et les temps de ce scénario sont copiés à la création.\n"
            "Ensuite le lien est rompu : les deux scénarios évoluent indépendamment.")
        grid.Add(self.base_ctrl, 1, wx.EXPAND)

        self.billing_label = wx.StaticText(self, label="Facturation outillage :")
        grid.Add(self.billing_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.billing_ctrl = wx.Choice(self, choices=["", ToolingBilling.REINVOICED.value, ToolingBilling.AMORTIZED.value])
        current = phase.tooling_billing if phase else None
        self.billing_ctrl.SetSelection(0 if current is None else 1 if current == ToolingBilling.REINVOICED else 2)
        self.billing_ctrl.SetToolTip(
            "Décomposé uniquement. Refacturé : bloc OUTILLAGE de l'offre, hors prix pièce.\n"
            "Amorti : intégré au prix pièce. Chaque ligne peut surcharger ce choix.")
        grid.Add(self.billing_ctrl, 1, wx.EXPAND)
        self._refresh_default_label()
        self._sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)

        # ---- Quantités (Taux horaire) : plage, saisie rapide ----
        self.qty_box = wx.StaticBoxSizer(wx.VERTICAL, self, label="Quantités (taille de lot)")
        hint = wx.StaticText(self, label="Tapez une quantité puis Entrée pour l'ajouter. Répétez pour chaque déclinaison.")
        hint.SetForegroundColour(wx.Colour(110, 110, 110))
        self.qty_box.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        entry_row = wx.BoxSizer(wx.HORIZONTAL)
        self.qty_entry = wx.TextCtrl(self, size=(100, -1), style=wx.TE_PROCESS_ENTER)
        self.qty_entry.SetHint("ex : 100")
        self.qty_entry.Bind(wx.EVT_TEXT_ENTER, self._on_qty_enter)
        entry_row.Add(self.qty_entry, 0, wx.RIGHT, 6)
        add_q = wx.Button(self, label="Ajouter", size=(80, -1))
        add_q.Bind(wx.EVT_BUTTON, self._on_qty_enter)
        entry_row.Add(add_q, 0, wx.RIGHT, 12)
        del_q = wx.Button(self, label="Retirer", size=(80, -1))
        del_q.Bind(wx.EVT_BUTTON, self._on_qty_remove)
        entry_row.Add(del_q, 0)
        self.qty_box.Add(entry_row, 0, wx.ALL, 4)

        self.qty_list = wx.ListBox(self, size=(-1, 110), style=wx.LB_SINGLE)
        self.qty_list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        self.qty_box.Add(self.qty_list, 1, wx.EXPAND | wx.ALL, 4)
        self._sizer.Add(self.qty_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        # Nouvelle phase : liste vide (on saisit ses déclinaisons). Édition : on
        # reprend les quantités existantes.
        initial = list(phase.sale_quantities) if (phase and phase.sale_quantities) else []
        self._set_quantities(initial)

        # ---- Volume annuel (Décomposé) : valeur unique ----
        self.vol_box = wx.StaticBoxSizer(wx.HORIZONTAL, self, label="Volume")
        self.vol_box.Add(wx.StaticText(self, label="Volume annuel :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        vol_init = DEFAULT_ANNUAL_VOLUME
        if phase and phase.serie_data and phase.serie_data.annual_volume:
            vol_init = phase.serie_data.annual_volume
        self.vol_entry = wx.TextCtrl(self, value=str(vol_init), size=(120, -1))
        self.vol_box.Add(self.vol_entry, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        self.vol_box.Add(wx.StaticText(self, label="pièces / an"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._sizer.Add(self.vol_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        btns.AddStretchSpacer(1)
        ok_btn = wx.Button(self, wx.ID_OK, "OK")
        ok_btn.SetDefault()
        btns.Add(ok_btn, 0, wx.RIGHT, 6)
        btns.Add(wx.Button(self, wx.ID_CANCEL, "Annuler"), 0)
        self._sizer.Add(btns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.SetSizer(self._sizer)
        self._update_mode()
        self.CentreOnParent()
        self.qty_entry.SetFocus()

    # ------------------------------------------------------------------ mode

    def _update_mode(self):
        """Affiche la plage (Taux horaire) ou le volume unique (Décomposé)."""
        is_serie = self.get_kind() == PhaseKind.SERIE
        self._sizer.Show(self.qty_box, not is_serie, recursive=True)
        self._sizer.Show(self.vol_box, is_serie, recursive=True)
        # Facturation outillage : seulement en Décomposé (jamais amorti en horaire)
        self.billing_label.Show(is_serie)
        self.billing_ctrl.Show(is_serie)
        # Version de départ : seulement pour créer une version Décomposé quand il en existe une à copier
        show_base = is_serie and not self._editing and bool(self._bases)
        self.base_label.Show(show_base)
        self.base_ctrl.Show(show_base)
        self._sizer.Layout()
        self.Fit()

    # ------------------------------------------------------------------ quantités

    def _set_quantities(self, quantities):
        self.qty_list.Clear()
        for q in sorted({int(q) for q in quantities if int(q) > 0}):
            self.qty_list.Append(str(q))

    def _current_quantities(self):
        return [int(self.qty_list.GetString(i)) for i in range(self.qty_list.GetCount())]

    def _add_quantity(self, value: int):
        if value <= 0:
            return
        existing = self._current_quantities()
        if value in existing:
            return
        self._set_quantities(existing + [value])

    def _on_qty_enter(self, event):
        raw = self.qty_entry.GetValue()
        # Autorise aussi un collage « 10 50 100 » ou « 10;50 »
        for chunk in raw.replace(",", " ").replace(";", " ").split():
            try:
                self._add_quantity(int(float(chunk)))
            except ValueError:
                continue
        self.qty_entry.ChangeValue("")
        self.qty_entry.SetFocus()

    def _on_qty_remove(self, event):
        sel = self.qty_list.GetSelection()
        if sel != wx.NOT_FOUND:
            self.qty_list.Delete(sel)

    def _on_list_key(self, event):
        if event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_BACK):
            self._on_qty_remove(event)
        else:
            event.Skip()

    def get_quantities(self):
        """Plage de quantités (Taux horaire), triée, au moins [1]."""
        qtys = self._current_quantities()
        return sorted(set(qtys)) if qtys else [1]

    def get_annual_volume(self) -> int:
        """Volume annuel unique (Décomposé)."""
        try:
            v = int(float(self.vol_entry.GetValue().replace(",", ".").replace(" ", "")))
        except ValueError:
            v = DEFAULT_ANNUAL_VOLUME
        return max(v, 1)

    # ------------------------------------------------------------------ type

    def _on_kind_changed(self, event):
        self._refresh_default_label()
        self._update_mode()

    def _refresh_default_label(self):
        default = default_tooling_billing(self.get_kind()).value
        self.billing_ctrl.SetString(0, f"Selon le type ({default})")
        if self.billing_ctrl.GetSelection() == wx.NOT_FOUND:
            self.billing_ctrl.SetSelection(0)

    def get_kind(self) -> PhaseKind:
        return PhaseKind.SERIE if self.kind_ctrl.GetSelection() == 1 else PhaseKind.LOT

    def get_base_version(self):
        """Indice de la version Taux horaire choisie comme départ (None : pas de choix proposé)."""
        if self.get_kind() != PhaseKind.SERIE or not self._bases or self._editing:
            return None
        sel = self.base_ctrl.GetSelection()
        return self._bases[sel][0] if sel != wx.NOT_FOUND else None

    def get_label(self) -> str:
        """Nom de la version tel que saisi (vide = « V<n> »)."""
        return self.label_ctrl.GetValue().strip()

    def get_sectors(self):
        """Normes suivies, sous forme de secteurs (Médical = ISO 13485, Aéronautique = ISO 9100) ; vide = Autre."""
        return normalize_sectors(s for s, chk in self.sector_chks.items() if chk.GetValue())

    def get_offer_comments(self) -> bool:
        """Les offres du scénario génèrent-elles les commentaires automatiques ?"""
        return self.comments_chk.GetValue()

    def get_prototype(self) -> bool:
        """Statut prototype du scénario."""
        return self.prototype_chk.GetValue()

    def get_phase_label(self) -> str:
        return self.get_label() or self.get_kind().calc_label

    def get_tooling_billing(self):
        return (None, ToolingBilling.REINVOICED, ToolingBilling.AMORTIZED)[self.billing_ctrl.GetSelection()]
