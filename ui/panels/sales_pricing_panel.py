# ui/panels/sales_pricing_panel.py
import wx
import wx.grid as gridlib
from domain.project import Project
from domain.cost import ConversionType, CostItem, CostType, PricingType
from ui.components.line_price_panel import LinePricePanel
from ui.components.result_summary_panel import ResultSummaryPanel
from domain import offers
from ui.components.ribbon_button import RibbonButton, ACCENT, TOOLING, SURFACE
from infrastructure.fx_rate import FxRate
from infrastructure.logging_service import get_module_logger

logger = get_module_logger("SalesPricing", "sales_pricing.log")

class SalesPricingPanel(wx.Panel):
    """Grid display of pricing results with a sidebar for full item properties."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.current_cost = None
        self.on_operation_updated = None
        self.on_generate_offer = None  # callback → MainFrame : nouvelle offre
        self.on_preview_offer = None   # callback → MainFrame : aperçu
        self.on_select_revision = None  # callback(entry) → recharge les coefficients d'un indice
        self.on_select_version = None   # callback(version_index)
        self.on_open_revision = None    # callback(entry) → ouvre le XLSX
        self._building_tree = False
        self._offer_mode = "new"
        self._build_ui()

    def _build_ui(self):
        """Même structure que l'onglet Gamme.

        Gauche : ruban puis arbre (ici les versions d'offre ; dans Gamme, la gamme).
        Droite, moitié haute : données de vente et coefficients, avec la synthèse des
        outillages sur leur droite. Moitié basse : analyse de prix de la sélection.
        """
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.offers_split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)

        # ---- Gauche : ruban OFFRES + arbre Version › Offre › Indice ----
        self.offers_panel = wx.Panel(self.offers_split)
        self.offers_panel.SetBackgroundColour(wx.WHITE)
        offers_sizer = wx.BoxSizer(wx.VERTICAL)

        ribbon = wx.Panel(self.offers_panel)
        ribbon.SetBackgroundColour(SURFACE)
        ribbon_sizer = wx.BoxSizer(wx.VERTICAL)
        caption = wx.StaticText(ribbon, label="OFFRES")
        caption.SetFont(wx.Font(wx.FontInfo(8).FaceName("Segoe UI").Bold()))
        caption.SetForegroundColour(wx.Colour(100, 116, 139))
        ribbon_sizer.Add(caption, 0, wx.LEFT | wx.TOP, 10)
        btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_preview = RibbonButton(ribbon, "👁", "Aperçu", accent=ACCENT, big=True, size=(100, 78))
        self.btn_preview.SetToolTip(
            "Ouvre l'offre XLSX en brouillon (BROUILLON / DRAFT) depuis un dossier temporaire.\n"
            "Aucun numéro de devis n'est consommé et rien n'est enregistré dans le projet.")
        self.btn_preview.Bind(wx.EVT_BUTTON, self._on_preview_offer)
        self.btn_new_offer = RibbonButton(ribbon, "💾", "Convertir en offre", accent=ACCENT, big=True, size=(120, 78))
        self.btn_new_offer.Bind(wx.EVT_BUTTON, self._on_generate_offer)
        for b in (self.btn_preview, self.btn_new_offer):
            btns.Add(b, 0, wx.RIGHT, 8)
        ribbon_sizer.Add(btns, 0, wx.ALL, 10)
        ribbon.SetSizer(ribbon_sizer)
        offers_sizer.Add(ribbon, 0, wx.EXPAND)
        offers_sizer.Add(wx.StaticLine(self.offers_panel), 0, wx.EXPAND)

        self.offer_tree = wx.TreeCtrl(self.offers_panel, style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT | wx.BORDER_NONE)
        self.offer_tree.SetFont(wx.Font(wx.FontInfo(10).FaceName("Segoe UI")))
        self.offer_tree.SetBackgroundColour(wx.WHITE)
        offers_sizer.Add(self.offer_tree, 1, wx.EXPAND | wx.ALL, 5)
        self.offer_hint = wx.StaticText(self.offers_panel, label="")
        self.offer_hint.SetForegroundColour(wx.Colour(100, 116, 139))
        offers_sizer.Add(self.offer_hint, 0, wx.ALL | wx.EXPAND, 10)
        self.offers_panel.SetSizer(offers_sizer)
        self.offer_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_offer_tree_selected)
        self.offer_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_offer_tree_activated)
        self.offer_tree.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self._on_offer_tree_right_click)

        # ---- Droite : haut = données de vente | outillages ; bas = analyse ----
        self.content_panel = wx.Panel(self.offers_split)
        content_sizer = wx.BoxSizer(wx.VERTICAL)

        # Message affiché quand la version active est chiffrée en Décomposé
        self.serie_notice = wx.StaticText(self.content_panel, label="")
        self.serie_notice.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.serie_notice.SetForegroundColour(wx.Colour(90, 90, 90))
        content_sizer.Add(self.serie_notice, 0, wx.ALL, 20)
        self.serie_notice.Hide()

        # Devise d'affichage (taux EUR/USD partagé par toute l'application)
        fx_bar = wx.BoxSizer(wx.HORIZONTAL)
        fx_bar.Add(wx.StaticText(self.content_panel, label="Devise :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        self.currency_choice = wx.Choice(self.content_panel, choices=["EUR (€)", "USD ($)"])
        self.currency_choice.SetSelection(1 if FxRate.currency == "USD" else 0)
        self.currency_choice.Bind(wx.EVT_CHOICE, self._on_currency_changed)
        fx_bar.Add(self.currency_choice, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        self.fx_label = wx.StaticText(self.content_panel, label=FxRate.label())
        self.fx_label.SetForegroundColour(wx.Colour(100, 116, 139))
        fx_bar.Add(self.fx_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.fx_refresh = wx.Button(self.content_panel, label="↻", size=(28, 24))
        self.fx_refresh.SetToolTip("Actualiser le taux EUR/USD (données BCE via Frankfurter)")
        self.fx_refresh.Bind(wx.EVT_BUTTON, lambda e: self._load_fx())
        fx_bar.Add(self.fx_refresh, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        content_sizer.Add(fx_bar, 0, wx.EXPAND)

        self.splitter = wx.SplitterWindow(self.content_panel, style=wx.SP_LIVE_UPDATE)      # haut / bas
        self.top_split = wx.SplitterWindow(self.splitter, style=wx.SP_LIVE_UPDATE)          # données | outillages

        # Haut gauche : données de vente et coefficient volume (éditable)
        self.grid_panel = wx.Panel(self.top_split)
        grid_sizer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self.grid_panel, label="Récapitulatif des Prix de Vente")
        self.title = title
        title.SetFont(wx.Font(wx.FontInfo(10).FaceName("Segoe UI").Bold()))
        grid_sizer.Add(title, 0, wx.ALL, 10)
        self.grid = gridlib.Grid(self.grid_panel)
        self.grid.CreateGrid(0, 2)
        self.grid.SetColLabelValue(0, "Opération")
        self.grid.SetColLabelValue(1, "Désignation")
        self.grid.SetMinSize((60, 120))
        grid_sizer.Add(self.grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.grid_panel.SetSizer(grid_sizer)

        # Haut droite : synthèse des outillages (internes + fournisseurs)
        self.tool_panel = wx.Panel(self.top_split)
        tool_sizer = wx.BoxSizer(wx.VERTICAL)
        tool_title = wx.StaticText(self.tool_panel, label="Synthèse outillage")
        tool_title.SetFont(wx.Font(wx.FontInfo(10).FaceName("Segoe UI").Bold()))
        tool_sizer.Add(tool_title, 0, wx.ALL, 10)
        self.tool_grid = gridlib.Grid(self.tool_panel)
        self.tool_grid.CreateGrid(0, 4)
        for col, label in enumerate(["Opération", "Désignation", "Facturation", "Montant (€)"]):
            self.tool_grid.SetColLabelValue(col, label)
        self.tool_grid.SetRowLabelSize(0)
        self.tool_grid.EnableEditing(False)
        self.tool_grid.SetMinSize((60, 90))
        tool_sizer.Add(self.tool_grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.tool_panel.SetSizer(tool_sizer)
        self.tool_grid.Bind(gridlib.EVT_GRID_SELECT_CELL, self._on_select_tool_cell)
        self.row_to_tool = {}

        # Largeur négative : le volet outillage garde sa largeur, le tableau de prix défile
        self.top_split.SplitVertically(self.grid_panel, self.tool_panel, -270)
        self.top_split.SetMinimumPaneSize(180)
        self.top_split.SetSashGravity(0.6)

        # Moitié basse : analyse de prix de la sélection (lecture seule)
        self.detail_panel = wx.Panel(self.splitter)
        self.detail_panel.SetBackgroundColour(wx.WHITE)
        self.detail_sizer = wx.BoxSizer(wx.VERTICAL)
        self.detail_title = wx.StaticText(self.detail_panel, label="Analyse du prix")
        self.detail_title.SetFont(wx.Font(wx.FontInfo(10).FaceName("Segoe UI").Bold()))
        self.detail_title.SetForegroundColour(wx.Colour(100, 116, 139))
        self.detail_sizer.Add(self.detail_title, 0, wx.ALL, 10)
        self.line_panel = LinePricePanel(self.detail_panel)
        self.detail_sizer.Add(self.line_panel, 1, wx.EXPAND)
        self.placeholder = wx.StaticText(
            self.detail_panel,
            label="Sélectionnez une ligne, un sous-total ou le total du tarif\npour voir le temps, le taux horaire final, le CA et la marge.")
        self.placeholder.SetForegroundColour(wx.Colour(100, 116, 139))
        self.detail_sizer.Add(self.placeholder, 0, wx.ALL, 20)
        self.line_panel.Hide()
        self.detail_panel.SetSizer(self.detail_sizer)

        self.splitter.SplitHorizontally(self.top_split, self.detail_panel, -330)
        self.splitter.SetMinimumPaneSize(150)
        self.splitter.SetSashGravity(0.5)
        content_sizer.Add(self.splitter, 1, wx.EXPAND)
        self.content_panel.SetSizer(content_sizer)

        self.offers_split.SplitVertically(self.offers_panel, self.content_panel, 340)   # = largeur du volet Gamme
        self.offers_split.SetMinimumPaneSize(250)
        main_sizer.Add(self.offers_split, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

        self.grid.Bind(gridlib.EVT_GRID_SELECT_CELL, self._on_select_cell)
        self.grid.Bind(gridlib.EVT_GRID_CELL_CHANGED, self._on_grid_cell_changed)
        self._update_offer_buttons()

    # ------------------------------------------------------------------ actions d'offre

    def _on_generate_offer(self, event):
        if callable(self.on_generate_offer):
            self.on_generate_offer()

    def _on_preview_offer(self, event):
        if self._offer_mode == "open":
            entry = self._entry_to_open()
            if entry and callable(self.on_open_revision):
                self.on_open_revision(entry)
        elif callable(self.on_preview_offer):
            self.on_preview_offer()

    def _entry_to_open(self):
        """Indice sélectionné (version courante) ou, à défaut, le dernier indice de la version."""
        data = self._selected_data()
        if data and data.get("type") == "revision" and data["version_index"] == self.project.current_version_index:
            return data["entry"]
        entries = [e for e in self.project.export_history if e.get("version_index", 1) == self.project.current_version_index]
        return entries[-1] if entries else None

    # ------------------------------------------------------------------ arbre des offres

    def _version_node_label(self, version) -> str:
        name = version.label.strip() if version.label and version.label.strip() else f"V{version.version_index}"
        lock = "  🔒" if self.project.is_version_frozen(version.version_index) else ""
        return f"{name} · {version.describe()}{lock}"

    def refresh_offers(self):
        """Reconstruit l'arbre Version › Offre › Indice depuis l'historique du projet."""
        self._building_tree = True
        try:
            tree = self.offer_tree
            tree.DeleteAllItems()
            root = tree.AddRoot("Offres")
            if not self.project:
                return
            groups = offers.group_offers(self.project.export_history)
            by_version = {}
            for g in groups:
                by_version.setdefault(g["version_index"], []).append(g)
            current_item = None
            for version in sorted(self.project.versions, key=lambda v: v.version_index):
                v_item = tree.AppendItem(root, self._version_node_label(version))
                tree.SetItemData(v_item, {"type": "version", "version_index": version.version_index})
                if version.version_index == self.project.current_version_index:
                    tree.SetItemBold(v_item, True)
                    current_item = v_item
                for g in by_version.get(version.version_index, []):
                    last = g["entries"][-1]
                    o_item = tree.AppendItem(v_item, f"{g['devis_ref']}  ·  {last.get('date', '')}")
                    tree.SetItemData(o_item, {"type": "offer", "devis_ref": g["devis_ref"],
                                              "version_index": version.version_index})
                    for entry in g["entries"]:
                        mark = "💾 " if entry.get("xlsx_data_b64") else "   "
                        archived = "  ⚠ archivée" if offers.is_legacy(entry) else ""
                        time_str = f" {entry['time']}" if entry.get("time") else ""
                        r_item = tree.AppendItem(
                            o_item, f"{mark}ind. {offers.revision_of(entry)} · {entry.get('date', '')}{time_str}{archived}")
                        tree.SetItemData(r_item, {"type": "revision", "entry": entry,
                                                  "devis_ref": g["devis_ref"], "version_index": version.version_index})
            tree.ExpandAll()
            if current_item is not None:
                tree.SelectItem(current_item)
        finally:
            self._building_tree = False
            self._update_offer_buttons()

    def _selected_data(self):
        item = self.offer_tree.GetSelection()
        return self.offer_tree.GetItemData(item) if item.IsOk() else None

    def _update_offer_buttons(self):
        """Boutons selon l'état de la version.

        Sans offre : « Aperçu » + « Convertir en offre » (indice A, gamme figée).
        Offre convertie, coefficients inchangés : seulement « Ouvrir l'offre ».
        Coefficients modifiés après conversion : l'indice suivant s'enregistre (B, C…) ; le
        changement d'indice est automatique, l'utilisateur n'en déclare jamais.
        """
        mode, ref, next_rev = "new", None, ""
        if self.project:
            idx = self.project.current_version_index
            ref = offers.latest_offer_ref(self.project.export_history, idx)
            if ref:
                mode = "open"
                last = [e for e in self.project.export_history
                        if e.get("devis_ref") == ref and e.get("version_index", 1) == idx][-1]
                coeffs = last.get("coeffs")
                if coeffs and not offers.same_coefficients(coeffs, offers.snapshot_coefficients(self.project.current_version)):
                    mode, next_rev = "revise", offers.next_revision(self.project.export_history, ref)
        self._offer_mode = mode
        if mode == "open":
            self.btn_preview.set_label("Ouvrir l'offre")
            self.btn_preview.SetToolTip("Ouvre le fichier XLSX remis au client (indice sélectionné, sinon le dernier).")
            self.btn_new_offer.Hide()
        else:
            self.btn_preview.set_label("Aperçu")
            self.btn_preview.SetToolTip(
                "Ouvre l'offre XLSX en brouillon (BROUILLON / DRAFT) depuis un dossier temporaire.\n"
                "Aucun numéro de devis n'est consommé et rien n'est enregistré dans le projet.")
            self.btn_new_offer.Show()
            if mode == "revise":
                self.btn_new_offer.set_label(f"Enregistrer l'indice {next_rev}")
                self.btn_new_offer.SetToolTip(
                    f"Les coefficients ont changé : enregistre l'indice {next_rev} de l'offre {ref}.")
            else:
                self.btn_new_offer.set_label("Convertir en offre")
                self.btn_new_offer.SetToolTip(
                    "Convertit cette version en offre (indice A) : nouveau numéro de devis, fichier XLSX choisi.\n"
                    "La gamme est alors figée : toute modification de gamme créera une nouvelle version, "
                    "toute modification de coefficients un nouvel indice.")
        self.offers_panel.Layout()
        self.btn_preview.GetParent().Layout()

    def _on_offer_tree_selected(self, event):
        if getattr(self, "_building_tree", False):
            return
        try:
            item = event.GetItem()
            data = self.offer_tree.GetItemData(item) if item.IsOk() else None
        except RuntimeError:        # arbre en cours de destruction (fermeture de la fenêtre)
            return
        self._update_offer_buttons()
        if not data:
            return
        if data["type"] == "revision":
            self._set_offer_hint(data["entry"])
            if callable(self.on_select_revision):
                wx.CallAfter(self.on_select_revision, data["entry"])   # hors de l'événement : l'arbre sera reconstruit
        else:
            self._set_offer_hint(None)
            if callable(self.on_select_version):
                wx.CallAfter(self.on_select_version, data["version_index"])
        self.offers_panel.Layout()

    LEGACY_WARNING = ("⚠ Offre antérieure à la gestion des indices (compatibilité) : consultation seule. "
                      "Ses coefficients n'ont pas été archivés ; seul le fichier XLSX remis au client est disponible.")

    def _set_offer_hint(self, entry):
        """Message sous l'arbre : avertissement de compatibilité pour une ancienne offre."""
        legacy = bool(entry) and offers.is_legacy(entry)
        self.offer_hint.SetLabel(self.LEGACY_WARNING if legacy else "")
        self.offer_hint.SetForegroundColour(wx.Colour(180, 90, 0) if legacy else wx.Colour(100, 116, 139))
        self.offer_hint.Wrap(max(self.offers_panel.GetClientSize().width - 20, 200))
        self.offers_panel.Layout()

    def _on_offer_tree_activated(self, event):
        data = self.offer_tree.GetItemData(event.GetItem()) if event.GetItem().IsOk() else None
        if data and data["type"] == "revision" and callable(self.on_open_revision):
            self.on_open_revision(data["entry"])

    def _on_offer_tree_right_click(self, event):
        item = event.GetItem()
        data = self.offer_tree.GetItemData(item) if item.IsOk() else None
        if not data or data["type"] != "revision":
            return
        self.offer_tree.SelectItem(item)
        entry = data["entry"]
        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, "Ouvrir le fichier XLSX")
        open_item.Enable(bool(entry.get("xlsx_data_b64")))
        self.Bind(wx.EVT_MENU, lambda e: self.on_open_revision(entry) if callable(self.on_open_revision) else None, open_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def select_revision(self, entry):
        """Sélectionne un indice dans l'arbre sans déclencher son chargement (None = rien)."""
        self._building_tree = True
        try:
            tree = self.offer_tree
            stack = [tree.GetRootItem()]
            while stack:
                item = stack.pop()
                child, cookie = tree.GetFirstChild(item)
                while child.IsOk():
                    data = tree.GetItemData(child)
                    if entry is not None and data and data.get("type") == "revision" and data["entry"] is entry:
                        tree.SelectItem(child)
                        tree.EnsureVisible(child)
                        self._set_offer_hint(entry)
                        return
                    stack.append(child)
                    child, cookie = tree.GetNextChild(item, cookie)
        finally:
            self._building_tree = False
            self._update_offer_buttons()

    def _load_fx(self):
        self.fx_refresh.Disable()
        self.fx_label.SetLabel("EUR/USD : chargement…")

        def done(ok, message):
            try:
                self.fx_label.SetLabel(message)
                self.fx_refresh.Enable()
                if ok and FxRate.currency == "USD":
                    self.refresh_data()
            except RuntimeError:
                pass
        FxRate.fetch_async(done)

    def _on_currency_changed(self, event):
        FxRate.currency = "USD" if self.currency_choice.GetSelection() == 1 else "EUR"
        if FxRate.currency == "USD" and not FxRate.rate:
            self._load_fx()
        self.refresh_data()

    @property
    def _fx(self) -> float:
        return FxRate.factor()

    @property
    def _sym(self) -> str:
        return FxRate.symbol()

    def load_project(self, project: Project):
        self.project = project
        self.refresh_data()
        self.refresh_offers()

    def _show_serie_notice(self, show: bool):
        if show:
            label = self.project.current_phase.display_label
            self.serie_notice.SetLabel(
                f"La version « {label} » est chiffrée en Décomposé (volume annuel) dans l'onglet « Décomposé ».\n"
                "Les offres de cette version se gèrent ici ; sélectionnez une version Taux horaire pour "
                "afficher le tarif par quantité.")
        if self.serie_notice.IsShown() != show or self.splitter.IsShown() == show:
            self.serie_notice.Show(show)
            self.splitter.Show(not show)
            self.content_panel.Layout()
            self.Layout()

    def refresh_data(self):
        if not self.project: return
        logger.debug("refresh_data start")
        phase = self.project.current_phase
        self._show_serie_notice(False)
        self.margin_row_idx = self.fixed_row_idx = self.total_row_idx = -1
        if phase.is_serie:
            self._refresh_serie_view(phase)
            return
        self.placeholder.SetLabel(
            "Sélectionnez une ligne, un sous-total ou le total du tarif\npour voir le temps, le taux horaire final, le CA et la marge.")
        self.title.SetLabel(f"Récapitulatif des Prix de Vente — {phase.display_label}")
        self.grid.BeginBatch()
        if self.grid.GetNumberRows() > 0:
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
            
        qtys = sorted(self.project.sale_quantities)
        target_cols = 2 + len(qtys)
        curr_cols = self.grid.GetNumberCols()
        if curr_cols < target_cols: self.grid.AppendCols(target_cols - curr_cols)
        elif curr_cols > target_cols: self.grid.DeleteCols(target_cols, curr_cols - target_cols)
        
        for i, q in enumerate(qtys):
            self.grid.SetColLabelValue(2 + i, f"Q{q} ({self._sym}/p)")
            
        self.row_to_cost = {}
        self.row_to_op = {}
        for op in self.project.operations:
            op_start_row = self.grid.GetNumberRows()
            for cost in op._get_active_costs():
                row = self.grid.GetNumberRows()
                self.grid.AppendRows(1)
                self.row_to_cost[row] = (cost, op)
                self.grid.SetCellValue(row, 0, op.code)
                self.grid.SetReadOnly(row, 0, True)
                self.grid.SetCellValue(row, 1, cost.name + ("  (amorti)" if cost.cost_type == CostType.TOOLING else ""))
                self.grid.SetReadOnly(row, 1, True)
                for i, q in enumerate(qtys):
                    val = cost.calculate_sale_price(q) # Unit price
                    self.grid.SetCellValue(row, 2 + i, f"{val * self._fx:.2f}")
                    self.grid.SetReadOnly(row, 2 + i, True)
                    self.grid.SetCellBackgroundColour(row, 2 + i, wx.Colour(240, 240, 255))
            
            # Add Operation Subtotal
            subtotal_row = self.grid.GetNumberRows()
            self.grid.AppendRows(1)
            self.row_to_op[subtotal_row] = op
            self.grid.SetCellValue(subtotal_row, 1, f"SOUS-TOTAL {op.code}")
            self.grid.SetReadOnly(subtotal_row, 1, True)
            self.grid.SetCellBackgroundColour(subtotal_row, 0, wx.Colour(235, 235, 235))
            self.grid.SetCellBackgroundColour(subtotal_row, 1, wx.Colour(235, 235, 235))
            self.grid.SetCellFont(subtotal_row, 1, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

            for i, q in enumerate(qtys):
                val = op.total_with_margins(q) # Unit price
                self.grid.SetCellValue(subtotal_row, 2 + i, f"{val * self._fx:.2f}")
                self.grid.SetReadOnly(subtotal_row, 2 + i, True)
                self.grid.SetCellBackgroundColour(subtotal_row, 2 + i, wx.Colour(235, 235, 235))
                self.grid.SetCellFont(subtotal_row, 2 + i, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        # Add Volume Margin rate row
        margin_row = self.grid.GetNumberRows()
        self.grid.AppendRows(1)
        self.grid.SetCellValue(margin_row, 1, "COEFF. MARGE / VOLUME")
        self.grid.SetReadOnly(margin_row, 1, True)
        self.grid.SetCellBackgroundColour(margin_row, 0, wx.Colour(255, 245, 230))
        self.grid.SetCellBackgroundColour(margin_row, 1, wx.Colour(255, 245, 230))
        self.grid.SetCellFont(margin_row, 1, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.margin_row_idx = margin_row

        for i, q in enumerate(qtys):
            rate = self.project.volume_margin_rates.get(q, 1.0)
            self.grid.SetCellValue(margin_row, 2 + i, f"{rate:.4f}")
            self.grid.SetCellBackgroundColour(margin_row, 2 + i, wx.Colour(255, 250, 240))
            self.grid.SetCellTextColour(margin_row, 2 + i, wx.Colour(200, 100, 0))
            self.grid.SetCellFont(margin_row, 2 + i, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            # This row is editable

        total_row = self.grid.GetNumberRows()
        self.grid.AppendRows(1)
        self.total_row_idx = total_row
        self.grid.SetCellValue(total_row, 1, f"PRIX DE VENTE TOTAL ({self._sym}/pièce)")
        self.grid.SetReadOnly(total_row, 1, True)
        self.grid.SetCellBackgroundColour(total_row, 1, wx.Colour(230, 230, 230))
        for i, q in enumerate(qtys):
            val = self.project.total_price(q) # Unit price
            self.grid.SetCellValue(total_row, 2 + i, f"{val * self._fx:.2f}")
            self.grid.SetReadOnly(total_row, 2 + i, True)
            self.grid.SetCellTextColour(total_row, 2 + i, wx.BLUE)
            self.grid.SetCellBackgroundColour(total_row, 2 + i, wx.Colour(230, 230, 230))
            self.grid.SetCellFont(total_row, 2 + i, wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        # Mode « prix fixé » : on saisit le prix pièce visé, le coefficient est recalculé
        fixed_row = self.grid.GetNumberRows()
        self.grid.AppendRows(1)
        self.fixed_row_idx = fixed_row
        self.grid.SetCellValue(fixed_row, 1, f"PRIX FIXÉ ({self._sym}/pièce) → ajuste le coeff.")
        self.grid.SetReadOnly(fixed_row, 1, True)
        self.grid.SetCellBackgroundColour(fixed_row, 0, wx.Colour(255, 245, 230))
        self.grid.SetCellBackgroundColour(fixed_row, 1, wx.Colour(255, 245, 230))
        for i, q in enumerate(qtys):
            self.grid.SetCellBackgroundColour(fixed_row, 2 + i, wx.Colour(255, 250, 240))
            self.grid.SetCellTextColour(fixed_row, 2 + i, wx.Colour(200, 100, 0))

        self.grid.AutoSizeColumns()
        self.grid.EndBatch()
        self._refresh_tooling_table()
        self.line_panel.refresh()      # l'analyse suit les modifications faites dans les autres onglets
        logger.debug("refresh_data done")

    def _refresh_serie_view(self, phase):
        """Version Décomposé : même écran que le Taux horaire (données en haut, outillage à droite,
        analyse en bas) ; les paramètres se règlent dans l'onglet Décomposé, les offres ici."""
        sd = self.project.serie_data
        self.row_to_cost, self.row_to_op = {}, {}
        self.title.SetLabel(f"Récapitulatif des Prix de Vente — {phase.display_label}")
        g = self.grid
        g.BeginBatch()
        if g.GetNumberRows() > 0:
            g.DeleteRows(0, g.GetNumberRows())
        for col, label in enumerate(["Poste", "Désignation", f"Coût ({self._sym}/p)", f"Prix ({self._sym}/p)", "Part"]):
            if col >= g.GetNumberCols():
                g.AppendCols(1)
            g.SetColLabelValue(col, label)
        if g.GetNumberCols() > 5:
            g.DeleteCols(5, g.GetNumberCols() - 5)
        if sd is None:
            g.EndBatch()
            self._refresh_tooling_table()
            self._clear_details()
            return
        pv = sd.selling_price_per_piece()
        rows = [
            ("MO directe production", sd.mo_cost_per_piece(), sd.mo_cost_per_piece()),
            ("CAPEX – amortissement", sd.capex_cost_per_piece(), sd.capex_price_per_piece()),
            ("Tooling / Outillages", sd.tooling_cost_per_piece(), sd.tooling_price_per_piece()),
            ("Setup / Démarrage", sd.setup_cost_per_piece(), sd.setup_price_per_piece()),
            ("Contrôle qualité", sd.control_cost_per_piece(), sd.control_cost_per_piece()),
            ("Matières premières / achats", sd.purchase_cost_per_piece(), sd.purchase_cost_per_piece() * (1 + sd.material_margin)),
            ("Logistique / Emballage", sd.logistics_cost_per_piece, sd.logistics_cost_per_piece * (1 + sd.logistics_margin)),
        ]
        rows.append(("SOUS-TOTAL (avant marge commerciale)", sd.total_cost_per_piece(), sd.subtotal_with_item_margins()))
        rows.append((f"PRIX DE VENTE (marge ciale {sd.global_commercial_margin * 100:.0f} %)", None, pv))
        bold = wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        g.AppendRows(len(rows))
        for r, (label, cost, price) in enumerate(rows):
            g.SetCellValue(r, 1, label)
            g.SetCellValue(r, 2, "" if cost is None else f"{cost * self._fx:.4f}")
            g.SetCellValue(r, 3, f"{price * self._fx:.4f}")
            g.SetCellValue(r, 4, f"{price / pv * 100:.1f} %" if pv > 0 and r < len(rows) - 2 else "")
            for c in range(5):
                g.SetReadOnly(r, c, True)
                if c >= 2:
                    g.SetCellAlignment(r, c, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
                if r >= len(rows) - 2:
                    g.SetCellFont(r, c, bold)
                    g.SetCellBackgroundColour(r, c, wx.Colour(230, 230, 230))
        self.total_row_idx = len(rows) - 1
        g.AutoSizeColumns()
        g.EndBatch()
        self._refresh_tooling_table()
        self._clear_details()
        self.placeholder.SetLabel(
            f"Volume annuel : {sd.annual_volume:,} pcs/an   ·   CA annuel : {sd.annual_revenue():,.0f} €\n"
            f"Programme (LOP) : {sd.program_lifetime_years} ans, {sd.total_program_volume():,} pcs, "
            f"CA {sd.total_program_revenue():,.0f} € pour un coût de {sd.total_program_cost():,.0f} €\n"
            f"Investissements : CAPEX {sd.total_capex_net_investment():,.0f} €, outillages "
            f"{sd.total_tooling_investment():,.0f} €, coût variable {sd.total_variable_program_cost():,.0f} €\n"
            "Les paramètres se règlent dans l'onglet « Décomposé »."
            .replace(",", " "))
        self.detail_panel.Layout()

    def _refresh_tooling_table(self):
        """Liste les outillages de la phase (un par ligne) et leurs totaux."""
        from domain.phase import ToolingBilling
        g = self.tool_grid
        g.BeginBatch()
        g.SetColLabelValue(3, f"Montant ({self._sym})")
        if g.GetNumberRows() > 0:
            g.DeleteRows(0, g.GetNumberRows())
        self.row_to_tool = {}
        totals = {ToolingBilling.REINVOICED: 0.0, ToolingBilling.AMORTIZED: 0.0}
        for op in self.project.operations:
            for tool in op.get_tooling_costs():
                billing = op._tooling_billing(tool)
                amount = float(tool.pricing.fixed_price or 0.0) if tool.pricing else 0.0
                totals[billing] += amount
                row = g.GetNumberRows()
                g.AppendRows(1)
                parent = getattr(tool, "supplier_parent", None)
                g.SetCellValue(row, 0, op.label)
                g.SetCellValue(row, 1, tool.name + ("  (fournisseur)" if parent else ""))
                g.SetCellValue(row, 2, billing.value)
                g.SetCellValue(row, 3, f"{amount * self._fx:,.2f}".replace(",", " "))
                g.SetCellAlignment(row, 3, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
                self.row_to_tool[row] = (parent or tool, op)

        bold = wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        total_rows = [("TOTAL OUTILLAGE", sum(totals.values()), wx.Colour(230, 230, 230))]
        if totals[ToolingBilling.AMORTIZED] > 0:
            total_rows = [
                ("dont refacturé (bloc OUTILLAGE de l'offre)", totals[ToolingBilling.REINVOICED], wx.Colour(245, 245, 245)),
                ("dont amorti dans le prix pièce", totals[ToolingBilling.AMORTIZED], wx.Colour(245, 245, 245)),
            ] + total_rows
        for label, value, colour in total_rows:
            row = g.GetNumberRows()
            g.AppendRows(1)
            g.SetCellValue(row, 1, label)
            g.SetCellValue(row, 3, f"{value * self._fx:,.2f}".replace(",", " "))
            g.SetCellAlignment(row, 3, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            for col in range(4):
                g.SetCellBackgroundColour(row, col, colour)
                g.SetCellFont(row, col, bold)
        g.AutoSizeColumns()
        g.EndBatch()

    def _on_select_tool_cell(self, event):
        entry = self.row_to_tool.get(event.GetRow())
        if entry:
            self._show_cost(*entry)
        event.Skip()

    def _on_select_cell(self, event):
        row = event.GetRow()
        if row in self.row_to_cost:
            cost, op = self.row_to_cost[row]
            self._show_cost(cost, op)
        elif row in self.row_to_op:
            self._show_operation(self.row_to_op[row])
        elif row == getattr(self, "total_row_idx", -1):
            self._show_project()
        else:
            self._clear_details()
        event.Skip()

    def _show_panel(self):
        self.placeholder.Hide()
        self.line_panel.Show()
        self.detail_panel.Layout()

    def _clear_details(self):
        self.line_panel.clear()
        self.line_panel.Hide()
        self.placeholder.Show()
        self.detail_panel.Layout()

    def _show_cost(self, cost, parent_op):
        self.current_cost, self.current_op = cost, parent_op
        self.line_panel.load_cost(cost, parent_op, self.project)
        self._show_panel()

    def _show_operation(self, op):
        self.current_cost, self.current_op = None, op
        self.line_panel.load_operation(op, self.project)
        self._show_panel()

    def _show_project(self):
        self.current_cost = self.current_op = None
        self.line_panel.load_project(self.project)
        self._show_panel()

    def _notify_main_frame(self):
        """Notifie le MainFrame des changements pour rafraîchir les autres panels."""
        if self.on_operation_updated:
            self.on_operation_updated(None)

    def _on_grid_cell_changed(self, event):
        row = event.GetRow()
        col = event.GetCol()
        if getattr(self, 'fixed_row_idx', -1) == row and col >= 2:
            try:
                target = float(self.grid.GetCellValue(row, col).replace(',', '.').replace(' ', '')) / self._fx
                q = sorted(self.project.sale_quantities)[col - 2]
                current_rate = self.project.volume_margin_rates.get(q, 1.0)
                if target <= 0:
                    raise ValueError
                self.project.volume_margin_rates[q] = 1.0
                base = self.project.total_price(q)
                if base <= 0:
                    self.project.volume_margin_rates[q] = current_rate
                    raise ValueError
                self.project.volume_margin_rates[q] = target / base
                self.refresh_data()
                self._notify_main_frame()
                self._update_offer_buttons()
            except ValueError:
                self.refresh_data()
            event.Skip()
            return
        if hasattr(self, 'margin_row_idx') and row == self.margin_row_idx and col >= 2:
            try:
                val = float(self.grid.GetCellValue(row, col).replace(',', '.'))
                qtys = sorted(self.project.sale_quantities)
                q = qtys[col - 2]
                self.project.volume_margin_rates[q] = val
                self.refresh_data()
                self._notify_main_frame()
                self._update_offer_buttons()
            except ValueError:
                self.refresh_data() # Reset to valid value
        event.Skip()
