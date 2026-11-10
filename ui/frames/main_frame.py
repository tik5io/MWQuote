# ui/main_frame.py
import wx
import os
import io
import datetime
import tempfile
from domain.project import Project
from ui.panels.project_panel import ProjectPanel, create_project_folder_interactive
from infrastructure.project_folder_service import ProjectFolderService
from ui.panels.operation_cost_editor_panel import OperationCostEditorPanel
from ui.panels.sales_pricing_panel import SalesPricingPanel
from ui.panels.serie_pricing_panel import SeriePricingPanel
from ui.components import trades
from ui.components.status_pills import StatusPills
from domain.client import SECTOR_MEDICAL, SECTOR_NORMS, PROTOTYPE_LABEL
from infrastructure.persistence import PersistenceService
from infrastructure.logging_service import clear_logs_directory
from infrastructure.export_service import ExportService
from infrastructure.database import Database
from infrastructure.indexer import Indexer
from infrastructure.configuration import ConfigurationService
from infrastructure.file_manager import FileManager
from core.app_icon import get_icon_path, load_icon_from_sheet, get_template_path
from infrastructure.template_manager import TemplateManager






class _CollapseRail(wx.Panel):
    """Rail étroit sur le bord gauche : replie / déplie le panneau Projet d'un clic.

    Toujours visible ; replié, il affiche le titre du panneau à la verticale. La couleur
    est celle du métier du panneau (voir ui.components.trades).
    """
    WIDTH = 24

    def __init__(self, parent, trade, caption, on_toggle):
        super().__init__(parent, size=(self.WIDTH, -1))
        self.SetMinSize((self.WIDTH, -1))
        self._trade, self._caption, self._on_toggle = trade, caption, on_toggle
        self._collapsed = False
        self._hover = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, lambda e: self._on_toggle())
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self._update_tooltip()

    def set_collapsed(self, collapsed: bool):
        self._collapsed = bool(collapsed)
        self._update_tooltip()
        self.Refresh()

    def _update_tooltip(self):
        self.SetToolTip("Déplier le panneau Projet (Ctrl+B)" if self._collapsed
                        else "Replier le panneau Projet pour gagner de la place (Ctrl+B)")

    def _set_hover(self, hover):
        self._hover = hover
        self.Refresh()

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        dc.SetBackground(wx.Brush(self._trade.tint if not self._hover else trades._mix(self._trade.colour, wx.WHITE, 0.8)))
        dc.Clear()
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(self._trade.colour))
        dc.DrawRectangle(0, 0, 3, h)
        dc.SetTextForeground(self._trade.text)
        dc.SetFont(wx.Font(wx.FontInfo(10).FaceName("Segoe UI").Bold()))
        glyph = "▶" if self._collapsed else "◀"
        gw, gh = dc.GetTextExtent(glyph)
        dc.DrawText(glyph, (w - gw) // 2 + 1, 10)
        if self._collapsed:
            dc.SetFont(wx.Font(wx.FontInfo(9).FaceName("Segoe UI").Bold()))
            text = self._caption.upper()
            tw, th = dc.GetTextExtent(text)
            dc.DrawRotatedText(text, (w - th) // 2 + 1, 44 + tw, 90)   # lu de bas en haut


class MainFrame(wx.Frame):
    """Fenêtre principale : fiche projet (amont, méthode, qualité, chiffrage)."""

    # Libellés d'onglets « Métier · Écran » (le métier donne aussi la couleur de la pastille)
    TAB_GAMME = "Méthode · Gamme"
    TAB_DECOMPOSE = "Chiffrage · Décomposé"
    TAB_TARIF = "Chiffrage · Tarif de vente"

    def __init__(self, project=None, clear_logs=False, filepath=None, new_quote=False):
        super().__init__(None, title="MWQuote", size=(1200, 800))
        
        if clear_logs:
            clear_logs_directory()

        self.project = project or Project(name="", reference="", client="")
        self.current_path = filepath
        self._dirty = False
        # Rappel optionnel appelé une fois la fiche réellement fermée : on_closed(chemin)
        self.on_closed = None

        # Services
        self.db = Database()
        self.indexer = Indexer(self.db)
        self.config = ConfigurationService.get_instance()
        self.template_manager = TemplateManager(self.db)
        self.export_service = ExportService(db=self.db)
        
        self._build_ui()
        self._create_menu_bar()
        self._connect_events()
        self._set_app_icon()
        
        if self.project:
            self._update_app_with_project(self.project)

        self.Show()

        # Nouvelle quote → création de la première phase (type de calcul + quantités).
        if new_quote:
            wx.CallAfter(self._on_new_quote_opened)

        # NB : plus de proposition automatique de création/export du dossier
        # projet à l'ouverture d'une fiche. L'export se fait uniquement sur
        # demande explicite via le bouton « Exporter… » du panneau projet.

    def _set_app_icon(self):
        try:
            icon_path = get_icon_path()
            if icon_path.exists():
                self.SetIcon(wx.Icon(str(icon_path), wx.BITMAP_TYPE_ICO))
        except Exception:
            pass

    def _create_menu_bar(self):
        """Crée la barre de menu"""
        menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        new_item = file_menu.Append(wx.ID_NEW, "&Nouveau\tCtrl+N")
        open_item = file_menu.Append(wx.ID_OPEN, "&Ouvrir...\tCtrl+O")
        save_item = file_menu.Append(wx.ID_SAVE, "&Enregistrer\tCtrl+S")
        save_as_item = file_menu.Append(wx.ID_SAVEAS, "Enregistrer &sous...\tCtrl+Shift+S")
        file_menu.AppendSeparator()
        duplicate_item = file_menu.Append(wx.ID_DUPLICATE, "&Dupliquer le projet")
        self._split_version_item = file_menu.Append(wx.ID_ANY, "Séparer le scénario courant en nouveau projet")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "&Quitter\tAlt+F4")

        menu_bar.Append(file_menu, "&Fichier")

        version_menu = wx.Menu()
        dup_version_item = version_menu.Append(wx.ID_ANY, "&Dupliquer le scénario courant")
        del_version_item = version_menu.Append(wx.ID_ANY, "&Supprimer le scénario courant…")
        menu_bar.Append(version_menu, "&Scénario")
        self.SetMenuBar(menu_bar)
        self.Bind(wx.EVT_MENU, lambda e: self._on_duplicate_version(), dup_version_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_delete_version(), del_version_item)

        # Bindings
        self.Bind(wx.EVT_MENU, self._on_new, new_item)
        self.Bind(wx.EVT_MENU, self._on_open, open_item)
        self.Bind(wx.EVT_MENU, self._on_save, save_item)
        self.Bind(wx.EVT_MENU, self._on_save_as, save_as_item)
        self.Bind(wx.EVT_MENU, self._on_duplicate, duplicate_item)
        self.Bind(wx.EVT_MENU, self._on_split_version, self._split_version_item)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), exit_item)
        self.Bind(wx.EVT_CLOSE, self._on_close)



    def _build_ui(self):
        """Construit l'interface utilisateur"""
        # Conteneur : rail de repli (bord gauche) + séparateur Projet | éditeur
        body = wx.Panel(self)
        splitter = wx.SplitterWindow(body, style=wx.SP_3D | wx.SP_LIVE_UPDATE)

        # Left column: Project information and preview
        left_panel = wx.Panel(splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        self.project_panel = ProjectPanel(left_panel)
        left_sizer.Add(self.project_panel, 1, wx.EXPAND)
        left_panel.SetSizer(left_sizer)

        # Right column: version bar + editing notebook
        right_panel = wx.Panel(splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Version bar ---
        self.version_bar = wx.Panel(right_panel, style=wx.BORDER_SIMPLE)
        self.version_bar.SetBackgroundColour(wx.Colour(230, 235, 245))
        self._version_bar_sizer = wx.WrapSizer(wx.HORIZONTAL)  # les versions passent à la ligne si besoin
        self._version_bar_sizer.Add(
            wx.StaticText(self.version_bar, label="  Scénarios :"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4
        )
        # Navigation : version précédente / suivante
        self.btn_prev_version = wx.Button(self.version_bar, label="◀", size=(30, 26))
        self.btn_prev_version.SetToolTip("Scénario précédent")
        self.btn_prev_version.Bind(wx.EVT_BUTTON, lambda e: self._navigate_version(-1))
        self.btn_next_version = wx.Button(self.version_bar, label="▶", size=(30, 26))
        self.btn_next_version.SetToolTip("Scénario suivant")
        self.btn_next_version.Bind(wx.EVT_BUTTON, lambda e: self._navigate_version(+1))
        self._version_bar_sizer.Add(self.btn_prev_version, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        self._version_bar_sizer.Add(self.btn_next_version, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
        self._version_btns = []  # list of (version_index, ToggleButton)
        self._switching_offer = False   # bascule d'offre/version en cours (garde contre la ré-entrance)

        # Alertes de cohérence de la version (prix manquant au-delà des pièces fournies…)
        self.phase_warn_lbl = wx.StaticText(self.version_bar, label="")
        self.phase_warn_lbl.SetForegroundColour(wx.Colour(190, 90, 0))
        self.phase_warn_lbl.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.phase_warn_lbl.Bind(wx.EVT_LEFT_DOWN, self._on_show_phase_warnings)
        self._phase_warnings = []
        self._version_bar_sizer.Add(self.phase_warn_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        # Légende du code couleur par métier (Projet / Méthode / Qualité / Chiffrage)
        self._version_bar_sizer.Add(trades.legend(self.version_bar, self.version_bar.GetBackgroundColour()),
                                    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        self.version_bar.SetSizer(self._version_bar_sizer)
        right_sizer.Add(self.version_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        # Bulles de statut du scénario sélectionné : mode de calcul, prototype, secteur, état de l'offre
        self.version_tags = StatusPills(right_panel)
        right_sizer.Add(self.version_tags, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # --- Notebook for editing tabs ---
        self.notebook = wx.Notebook(right_panel)
        # Chaque onglet porte le métier qui le travaille : pastille de couleur + « Métier · Écran ».
        self._trade_images = trades.TradeImages()
        self.notebook.SetImageList(self._trade_images.imagelist)

        self.editor_panel = OperationCostEditorPanel(self.notebook)
        self.editor_panel.set_database(self.db)
        self.notebook.AddPage(self.editor_panel, self.TAB_GAMME, imageId=self._trade_images.index(trades.METHODE))

        self.sales_panel = SalesPricingPanel(self.notebook)
        self.notebook.AddPage(self.sales_panel, self.TAB_TARIF, imageId=self._trade_images.index(trades.CHIFFRAGE))

        # Le panneau Décomposé n'a pas d'onglet propre : dans une version Décomposé il prend la
        # place de l'onglet Gamme (voir _update_gamme_tab).
        self.serie_panel = SeriePricingPanel(self.notebook)
        self.serie_panel.Hide()

        right_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        right_panel.SetSizer(right_sizer)

        self.splitter, self._left_panel, self._right_panel = splitter, left_panel, right_panel
        self._left_width = 400
        splitter.SplitVertically(left_panel, right_panel)
        splitter.SetSashPosition(self._left_width)
        splitter.SetMinimumPaneSize(250)

        self._rail = _CollapseRail(body, trades.PROJET, "Projet · Contexte et plans", self._toggle_project_panel)
        body_sizer = wx.BoxSizer(wx.HORIZONTAL)
        body_sizer.Add(self._rail, 0, wx.EXPAND)
        body_sizer.Add(splitter, 1, wx.EXPAND)
        body.SetSizer(body_sizer)

        # Ctrl+B : replier / déplier ; l'état est mémorisé d'une session à l'autre
        toggle_id = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_project_panel(), id=toggle_id)
        self.SetAcceleratorTable(wx.AcceleratorTable([(wx.ACCEL_CTRL, ord("B"), toggle_id)]))
        if self.config.config.get("ui_project_panel_collapsed"):
            self._set_project_panel_collapsed(True, save=False)

    def _toggle_project_panel(self):
        self._set_project_panel_collapsed(self.splitter.IsSplit())

    def _set_project_panel_collapsed(self, collapsed: bool, save: bool = True):
        """Replie le panneau Projet sur le bord gauche (collapsed=True) ou le rétablit à sa largeur."""
        splitter = self.splitter
        if collapsed and splitter.IsSplit():
            self._left_width = max(splitter.GetSashPosition(), 250)   # mémorisée pour le retour
            splitter.Unsplit(self._left_panel)
        elif not collapsed and not splitter.IsSplit():
            self._left_panel.Show()
            splitter.SplitVertically(self._left_panel, self._right_panel, self._left_width)
        self._rail.set_collapsed(collapsed)
        if save:
            self.config.config["ui_project_panel_collapsed"] = bool(collapsed)
            self.config.save()
        self.Layout()

    def _connect_events(self):
        """Connecte les événements entre les panels"""
        self.editor_panel.on_operation_updated = self._on_operation_updated
        self.sales_panel.on_operation_updated = self._on_operation_updated
        self.project_panel.on_export_fabrication = self._on_export_fabrication_quality
        self.serie_panel.on_serie_updated = self._on_serie_updated
        self.serie_panel.on_steps_changed = self.editor_panel.reload_selected_properties

        # Génération d'offres depuis les onglets dédiés
        self.sales_panel.on_generate_offer = self._on_new_offer
        self.sales_panel.on_preview_offer = self._on_preview_current
        self.sales_panel.on_select_revision = self._on_offer_revision_selected
        self.sales_panel.on_select_version = self._on_offer_version_selected
        self.sales_panel.on_open_revision = self._open_offer_xlsx
        self.sales_panel.on_export_quality = self._on_export_fabrication_quality
        self.sales_panel.on_new_revision = self._on_create_revision
        self.sales_panel.on_comment_changed = self._mark_dirty
        self.editor_panel.on_request_new_version = lambda: self._on_add_version(None)
        self.serie_panel.on_request_new_version = lambda: self._on_add_version(None)
        self.serie_panel.on_generate_serie_offer = self._on_export_serie_xlsx
        self.serie_panel.on_preview_serie_offer = lambda: self._on_preview_offer(serie_offer=True)

        def on_proj_changed():
            self.editor_panel.update_root_label()
            self._mark_dirty()

        self.project_panel.on_project_changed = on_proj_changed

    def _update_app_with_project(self, project):
        """Met à jour tous les panels avec un nouveau projet"""
        self.project = project
        self._rebuild_version_bar()
        self._reload_all_panels()
        self._update_title()

    def _reload_all_panels(self, editor_selection_path=None):
        """Recharge tous les panels depuis le projet courant.

        Args:
            editor_selection_path: si fourni, restaure cette sélection dans l'arbre
                Gamme & Coûts (identifiant (op_index, cost_key) capturé AVANT la
                bascule de version) → rendu fluide au changement de version.
        """
        self.project_panel.load_project(self.project)
        self.editor_panel.load_project(self.project)
        self.sales_panel.load_project(self.project)
        self.serie_panel.load_project(self.project)
        if editor_selection_path is not None:
            self.editor_panel.restore_selection_path(editor_selection_path)
        self._update_gamme_tab()
        self._apply_freeze_state()

    def _update_gamme_tab(self):
        """Premier onglet : « Gamme » en Taux horaire, « Décomposé » dans une version Décomposé.

        Dans une version Décomposé, la structure et les temps ont été copiés à la
        création de la version : le panneau Décomposé les exploite, il n'y a plus de
        gamme à éditer à part.
        """
        if not self.project:
            return
        is_serie = self.project.current_phase.is_serie
        wanted, other = (self.serie_panel, self.editor_panel) if is_serie else (self.editor_panel, self.serie_panel)
        title = self.TAB_DECOMPOSE if is_serie else self.TAB_GAMME
        image = self._trade_images.index(trades.CHIFFRAGE if is_serie else trades.METHODE)
        if self.notebook.FindPage(wanted) == 0:
            self.notebook.SetPageText(0, title)
            self.notebook.SetPageImage(0, image)
            return
        selected = self.notebook.GetSelection()
        current_page = self.notebook.GetPage(selected) if selected not in (wx.NOT_FOUND, 0) else None
        old = self.notebook.FindPage(other)
        if old != wx.NOT_FOUND:
            self.notebook.RemovePage(old)
        other.Hide()
        show_it = selected in (0, wx.NOT_FOUND)
        self.notebook.InsertPage(0, wanted, title, select=show_it, imageId=image)
        # Ne jamais afficher de force : sur un autre onglet (Tarif…), la page insérée
        # recouvrirait l'onglet courant.
        wanted.Show(show_it)
        self.notebook.Layout()
        if not show_it and current_page is not None:
            idx = self.notebook.FindPage(current_page)
            if idx != wx.NOT_FOUND:
                self.notebook.SetSelection(idx)
                current_page.Show()

    # ------------------------------------------------------------------ #
    # Offres (indices) et gel de version                                    #
    # ------------------------------------------------------------------ #

    def _apply_freeze_state(self):
        """Une version portant une offre émise est figée : gamme en lecture seule."""
        if not self.project:
            return
        frozen = self.project.is_version_frozen()
        self.editor_panel.set_locked(frozen, self.project.version_frozen_by() or "")
        self.serie_panel.set_locked(frozen and self.project.current_phase.is_serie, self.project.version_frozen_by() or "")

    def _on_new_offer(self):
        """Ruban « Convertir en offre » : scénario sans offre → nouvelle offre (indice A, gamme figée).

        Un scénario déjà converti ne se re-convertit pas : un nouvel indice se crée par
        « Créer un nouvel indice » (ajustement explicite des coefficients).
        """
        from domain import offers
        if not self.project:
            return
        ref = offers.latest_offer_ref(self.project.export_history, self.project.current_version_index)
        if ref:
            self._on_create_revision(ref)
            return
        self._on_export_xlsx(serie_offer=self.project.current_phase.is_serie)

    def _on_create_revision(self, devis_ref=None):
        """« Créer un nouvel indice » d'une offre archivée : ajuste les coefficients puis génère l'offre.

        Les coefficients de départ sont ceux de l'indice sélectionné. Ils ne sont appliqués au
        scénario qu'avec la génération de l'offre : si l'export est annulé ou échoue, on revient
        aux coefficients d'origine (un coefficient modifié sans indice n'a pas de raison d'être).
        """
        from domain import offers
        from ui.dialogs.new_revision_dialog import NewRevisionDialog
        if not self.project:
            return
        version = self.project.current_version
        idx = version.version_index
        history = self.project.export_history
        ref = devis_ref or offers.latest_offer_ref(history, idx)
        if not ref:
            return
        next_rev = offers.next_revision(history, ref)
        entries = [e for e in history if e.get("devis_ref") == ref and e.get("version_index", 1) == idx]
        selected = self.sales_panel._selected_data()
        if selected and selected.get("type") == "revision" and selected.get("devis_ref") == ref:
            from_rev = offers.revision_of(selected["entry"])
        else:
            from_rev = offers.revision_of(entries[-1]) if entries else None

        before = offers.snapshot_coefficients(version)
        lot_base, serie_fn = {}, None
        if version.is_serie:
            sd = self.project.serie_data

            def serie_fn(margin, sd=sd):
                previous = sd.global_commercial_margin
                sd.global_commercial_margin = margin
                try:
                    return sd.selling_price_per_piece()
                finally:
                    sd.global_commercial_margin = previous
        else:
            # Prix pièce à coefficient 1 : de quoi lier coefficient et prix dans la fenêtre
            rates = self.project.volume_margin_rates
            saved = dict(rates)
            try:
                for q in self.project.sale_quantities:
                    rates[q] = 1.0
                lot_base = {q: self.project.total_price(q) for q in self.project.sale_quantities}
            finally:
                rates.clear()
                rates.update(saved)

        dlg = NewRevisionDialog(self, ref, next_rev, before, from_revision=from_rev, lot_base_prices=lot_base,
                                serie_price_fn=serie_fn, fx=self.sales_panel._fx, symbol=self.sales_panel._sym)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            after = dlg.get_coefficients()
        finally:
            dlg.Destroy()

        offers.apply_snapshot(version, after)
        self._reload_keeping_selection()
        issued_before = len(self.project.export_history)
        self._on_export_xlsx(serie_offer=version.is_serie, revise_ref=ref)
        if len(self.project.export_history) == issued_before:
            # Export annulé ou en échec : pas d'indice créé, on rétablit les coefficients d'origine
            offers.apply_snapshot(self.project.current_version, before)
            self._reload_keeping_selection()

    def _on_preview_current(self):
        if self.project:
            self._on_preview_offer(serie_offer=self.project.current_phase.is_serie)

    def _after_offer_issued(self, was_frozen: bool):
        """Offre émise : l'arbre se met à jour et la gamme se fige (avec information au 1er passage)."""
        # Pas de popup : le verrouillage est visible dans l'éditeur (bandeau « figée »).
        self._reload_keeping_selection()

    def _on_offer_version_selected(self, version_index: int):
        """Clic sur une version dans l'arbre d'offres : on bascule dessus."""
        if self._switching_offer:
            return
        if self.project and version_index != self.project.current_version_index:
            self._switching_offer = True
            try:
                self._on_version_selected(version_index)
            finally:
                self._switching_offer = False

    def _on_offer_revision_selected(self, entry: dict):
        """Clic sur un indice : bascule sur sa version et recharge ses paramètres de vente."""
        if self._switching_offer:       # ré-entrance (boucle de messages imbriquée) : ne pas reconstruire deux fois
            return
        self._switching_offer = True
        try:
            self._switch_to_revision(entry)
        finally:
            self._switching_offer = False

    def _switch_to_revision(self, entry: dict):
        from domain import offers
        if not self.project:
            return
        idx = entry.get("version_index", 1)
        if idx != self.project.current_version_index:
            self._on_version_selected(idx)
            if self.project.current_version_index != idx:
                return                      # bascule annulée (modifications non enregistrées)
        coeffs = entry.get("coeffs")
        if not coeffs:
            self.sales_panel.select_revision(entry)
            return
        version = self.project.current_version
        current = offers.snapshot_coefficients(version)
        if not offers.same_coefficients(current, coeffs):
            known = [e.get("coeffs") for e in self.project.export_history if e.get("version_index", 1) == idx]
            if not any(offers.same_coefficients(current, k) for k in known):
                if wx.MessageBox(
                        "Les paramètres de vente actuels n'ont été émis dans aucune offre.\n"
                        f"Les remplacer par ceux de l'indice {offers.revision_of(entry)} de {entry.get('devis_ref')} ?",
                        "Recharger l'indice", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION) != wx.YES:
                    self.sales_panel.select_revision(None)
                    return
            if offers.apply_snapshot(version, coeffs):
                self._reload_keeping_selection()
                self._mark_dirty()
        self.sales_panel.select_revision(entry)

    def _open_offer_xlsx(self, entry: dict):
        """Ouvre le XLSX remis au client pour cet indice (copie temporaire nommée d'après la référence d'offre)."""
        from infrastructure.offer_files import offer_workbook_path
        try:
            path = offer_workbook_path(entry)
        except ValueError:
            wx.MessageBox("Aucun fichier XLSX stocké pour cette offre.\n"
                          "Les offres futures sont automatiquement sauvegardées.",
                          "Fichier non disponible", wx.OK | wx.ICON_INFORMATION)
            return
        try:
            os.startfile(path)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'ouverture du XLSX :\n{e}", "Erreur", wx.OK | wx.ICON_ERROR)

    # ------------------------------------------------------------------ #
    # Version management                                                    #
    # ------------------------------------------------------------------ #

    def _rebuild_version_bar(self):
        """Reconstruit les boutons de version dans la barre."""
        # Remove existing version buttons (keep label and spacer)
        for _, btn in self._version_btns:
            self._version_bar_sizer.Detach(btn)
            btn.Destroy()
        self._version_btns.clear()

        if not self.project:
            self.version_bar.Layout()
            return

        current_idx = self.project.current_version_index
        sizer = self._version_bar_sizer

        # Insert version buttons after the label (index 1)
        insert_pos = 3           # après le libellé et les deux boutons de navigation
        for version in sorted(self.project.versions, key=lambda v: v.version_index):
            v_idx = version.version_index
            btn = wx.ToggleButton(self.version_bar, label=self._version_button_label(version), size=(-1, 26))
            btn.SetValue(v_idx == current_idx)
            btn.SetToolTip(
                f"Scénario {v_idx}" + (f" — {version.label}" if version.label.strip() else "") +
                f"\n{version.describe()}" +
                f"\nOutillage : {version.phase.effective_tooling_billing.value}" +
                (f"\n🔒 Gamme figée (offre {self.project.version_frozen_by(v_idx)})"
                 if self.project.is_version_frozen(v_idx) else "") +
                f"\nCréée le {version.created_at[:10]}" +
                (f"\nDepuis S{version.created_from_version}" if version.created_from_version else "") +
                "\n\nDouble-clic : modifier (nom, quantités)\nClic droit : dupliquer / supprimer"
            )
            v_idx_captured = v_idx
            btn.Bind(wx.EVT_TOGGLEBUTTON, lambda e, idx=v_idx_captured: self._on_version_selected(idx))
            btn.Bind(wx.EVT_LEFT_DCLICK, lambda e, idx=v_idx_captured: self._on_edit_version(idx))
            btn.Bind(wx.EVT_RIGHT_UP, lambda e, idx=v_idx_captured: self._on_version_context_menu(idx))
            sizer.Insert(insert_pos, btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
            self._version_btns.append((v_idx, btn))
            insert_pos += 1

        # "+" button to create a new version
        add_btn = wx.Button(self.version_bar, label="+  Nouveau scénario", size=(-1, 26))
        add_btn.SetToolTip("Créer un nouveau scénario (copie de la gamme courante) : autres quantités, "
                           "autre mode de calcul (Taux horaire / Décomposé)")
        add_btn.Bind(wx.EVT_BUTTON, self._on_add_version)
        sizer.Insert(insert_pos, add_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        self._version_btns.append((-1, add_btn))  # -1 = not a real version btn

        # Dupliquer / supprimer : agissent sur la version courante
        dup_btn = wx.Button(self.version_bar, label="Dupliquer", size=(-1, 26))
        dup_btn.SetToolTip("Dupliquer le scénario courant (copie modifiable, jamais figée)")
        dup_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_duplicate_version())
        sizer.Insert(insert_pos + 1, dup_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self._version_btns.append((-1, dup_btn))
        del_btn = wx.Button(self.version_bar, label="Supprimer", size=(-1, 26))
        del_btn.SetToolTip("Supprimer le scénario courant (avertit si une offre l'a figé)")
        del_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_delete_version())
        del_btn.Enable(len(self.project.versions) > 1)
        sizer.Insert(insert_pos + 2, del_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._version_btns.append((-1, del_btn))

        self._refresh_phase_warnings()
        self._update_version_nav()
        self._refresh_version_tags()
        self.version_bar.Layout()
        self.version_bar.GetParent().Layout()

    # Couleurs des bulles de statut (hors métiers) : repères neutres
    _TAG_GREY = wx.Colour(100, 116, 139)
    _TAG_SLATE = wx.Colour(51, 65, 85)

    def _refresh_version_tags(self):
        """Bulles du scénario sélectionné : mode de calcul, statut (prototype, offre émise), secteur."""
        if not self.project or not hasattr(self, "version_tags"):
            return
        version = self.project.current_version
        tags = [(version.display_mode, trades.CHIFFRAGE.colour,
                 "Mode de calcul de ce scénario (Taux horaire : quantités commandées ; Décomposé : volume annuel).")]
        if version.is_prototype:
            tags.append(("Prototype", trades.PROJET.colour, PROTOTYPE_LABEL))
        if version.sectors:
            for sector in version.sectors:
                norm = SECTOR_NORMS[sector]
                colour = trades.QUALITE.colour if sector == SECTOR_MEDICAL else trades.METHODE.colour
                tags.append((norm, colour, f"Norme suivie : {norm} (secteur {sector.lower()}). "
                                           "Traçabilité et suivi applicables, mentionnés sur l'offre."))
        else:
            tags.append(("Autre", self._TAG_GREY,
                         "Secteur « Autre » : aucune norme ISO 13485 ou ISO 9100 suivie "
                         "(traçabilité et suivi non applicables)."))
        frozen_by = self.project.version_frozen_by(version.version_index)
        if frozen_by:
            tags.append((f"Offre émise · {frozen_by}", self._TAG_SLATE,
                         "Une offre a été émise : la gamme est figée (créer un nouveau scénario pour la modifier)."))
        else:
            tags.append(("Brouillon", wx.Colour(148, 163, 184), "Aucune offre émise sur ce scénario."))
        if not version.offer_comments:
            tags.append(("Sans commentaires auto", self._TAG_GREY,
                         "Les mentions de traçabilité et de prototype ne sont pas ajoutées aux offres de ce scénario."))
        self.version_tags.set_tags(tags)

    def _version_order(self):
        return [v.version_index for v in sorted(self.project.versions, key=lambda v: v.version_index)] if self.project else []

    def _update_version_nav(self):
        order = self._version_order()
        pos = order.index(self.project.current_version_index) if self.project and self.project.current_version_index in order else -1
        self.btn_prev_version.Enable(pos > 0)
        self.btn_next_version.Enable(0 <= pos < len(order) - 1)

    def _navigate_version(self, step: int):
        """◀ ▶ : passe à la version précédente / suivante."""
        order = self._version_order()
        if not order or self.project.current_version_index not in order:
            return
        pos = order.index(self.project.current_version_index) + step
        if 0 <= pos < len(order):
            self._on_version_selected(order[pos])

    # ------------------------------------------------------------------ #
    # Configuration de vente de la version (mode de calcul, quantités)      #
    # ------------------------------------------------------------------ #

    def _version_button_label(self, version) -> str:
        """« S1 · Taux horaire · 10 / 100 pc » — ou le nom donné au scénario ; 🔒 si figée."""
        name = version.label.strip() if version.label.strip() else f"S{version.version_index}"
        qtys = sorted(version.phase.sale_quantities or [])
        if version.is_serie:
            sd = version.phase.serie_data
            detail = f"{int(sd.annual_volume):,} pc/an".replace(",", " ") if sd else "—"
        else:
            shown = [f"{q:,}".replace(",", " ") for q in qtys[:3]]
            detail = (" / ".join(shown) + (" …" if len(qtys) > 3 else "") + " pc") if qtys else "—"
        lock = " 🔒" if self.project and self.project.is_version_frozen(version.version_index) else ""
        proto = " · Proto" if version.is_prototype else ""
        return f"{name} · {version.display_mode} · {detail}{proto}{lock}"

    def _refresh_phase_warnings(self):
        """Indicateur des incohérences de la version (prix manquant au-delà des pièces fournies…)."""
        from domain.quote_validator import QuoteValidator
        try:
            self._phase_warnings = QuoteValidator.phase_warnings(self.project) if self.project else []
        except Exception:
            self._phase_warnings = []
        n = len(self._phase_warnings)
        self.phase_warn_lbl.SetLabel(f"⚠ {n} point{'s' if n > 1 else ''} à vérifier" if n else "")
        self.phase_warn_lbl.SetToolTip("\n".join(w.message for w in self._phase_warnings) if n else "")
        self.version_bar.Layout()

    def _on_show_phase_warnings(self, event):
        if not self._phase_warnings:
            return
        text = "\n\n".join(f"• {w.message}" for w in self._phase_warnings)
        wx.MessageBox(text, "Cohérence du scénario", wx.OK | wx.ICON_INFORMATION)

    def _reload_keeping_selection(self):
        sel_path = self.editor_panel.get_selection_path()
        tab_idx = self.notebook.GetSelection()
        self._rebuild_version_bar()
        self._reload_all_panels(editor_selection_path=sel_path)
        if tab_idx != wx.NOT_FOUND:
            self.notebook.SetSelection(tab_idx)
        self.version_bar.GetParent().Layout()

    def _on_edit_version(self, version_index: int):
        """Double-clic sur une version : nom, quantités / volume, facturation de l'outillage.

        Le mode de calcul ne change pas ici : pour vendre la gamme autrement,
        on crée une nouvelle version.
        """
        if not self.project:
            return
        from domain.phase import PhaseKind
        from ui.dialogs.phase_dialog import PhaseDialog
        version = next((v for v in self.project.versions if v.version_index == version_index), None)
        if version is None:
            return
        phase = version.phase
        dlg = PhaseDialog(self, phase, title=f"Modifier le scénario S{version_index}", label=version.label,
                          prototype=version.is_prototype, sectors=version.sectors,
                          offer_comments=version.offer_comments)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            version.label = dlg.get_label()
            version.is_prototype = dlg.get_prototype()
            version.sectors = dlg.get_sectors()
            version.offer_comments = dlg.get_offer_comments()
            phase.label = version.label or phase.label
            phase.tooling_billing = dlg.get_tooling_billing()
            if version.is_serie:
                if phase.serie_data:
                    phase.serie_data.annual_volume = dlg.get_annual_volume()
            else:
                phase.sale_quantities = dlg.get_quantities()
        finally:
            dlg.Destroy()
        self._reload_keeping_selection()
        self.sales_panel.refresh_offers()   # l'arbre d'offres affiche le nom de version
        self._mark_dirty()
        self._update_title()

    def _on_version_selected(self, version_index: int):
        """Bascule vers une version du projet."""
        if not self.project or self.project.current_version_index == version_index:
            # Re-enforce toggle state (prevent deselecting active)
            for idx, btn in self._version_btns:
                if idx == version_index and hasattr(btn, 'SetValue'):
                    btn.SetValue(True)
            return

        # Version figée par une offre : la gamme n'est plus éditable, rien à confirmer
        if self._dirty and not self.project.is_version_frozen():
            res = wx.MessageBox(
                "Des modifications n'ont pas été enregistrées.\nSouhaitez-vous enregistrer avant de changer de scénario ?",
                "Modifications non enregistrées",
                wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
            )
            if res == wx.CANCEL:
                # Annuler : re-sélectionner la version courante dans la barre
                self._rebuild_version_bar()
                return
            if res == wx.YES:
                if not self._save_project(allow_dialog=True):
                    self._rebuild_version_bar()
                    return

        was_frozen = self.project.is_version_frozen()
        # Capturer AVANT la bascule : current_data pointe encore vers la version
        # courante, donc get_selection_path() peut résoudre la position op/coût.
        sel_path = self.editor_panel.get_selection_path()
        tab_idx = self.notebook.GetSelection()

        self.project.switch_to_version(version_index)
        self._rebuild_version_bar()
        # Bascule fluide : conserver la sélection arbre (même position op/coût) + l'onglet actif
        self._reload_all_panels(editor_selection_path=sel_path)
        if tab_idx != wx.NOT_FOUND:
            self.notebook.SetSelection(tab_idx)
        self._dirty = self._dirty and was_frozen     # figée : l'état à enregistrer est conservé, sans confirmation
        self._update_title()

    def _on_add_version(self, event):
        """Crée une nouvelle version à partir de la version courante."""
        if not self.project:
            return

        # Version figée par une offre : la gamme n'est plus éditable, rien à confirmer
        if self._dirty and not self.project.is_version_frozen():
            res = wx.MessageBox(
                "Des modifications n'ont pas été enregistrées.\nSouhaitez-vous enregistrer avant de créer un nouveau scénario ?",
                "Modifications non enregistrées",
                wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
            )
            if res == wx.CANCEL:
                return
            if res == wx.YES:
                if not self._save_project(allow_dialog=True):
                    return

        from ui.dialogs.phase_dialog import PhaseDialog
        # Versions Taux horaire proposables comme départ d'une version Décomposé
        bases = [(v.version_index, self._version_button_label(v)) for v in
                 sorted(self.project.versions, key=lambda v: v.version_index) if not v.is_serie]
        cur = self.project.current_version
        default_base = cur.version_index if not cur.is_serie else (bases[0][0] if bases else None)
        dlg = PhaseDialog(self, title="Nouveau scénario", template=self.project.current_phase,
                          bases=bases, default_base=default_base, prototype=cur.is_prototype,
                          sectors=cur.sectors, offer_comments=cur.offer_comments)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            label = dlg.get_label()
            phase_label = dlg.get_phase_label()
            kind = dlg.get_kind()
            qtys = dlg.get_quantities()
            volume = dlg.get_annual_volume()
            billing = dlg.get_tooling_billing()
            base_version = dlg.get_base_version()
            prototype = dlg.get_prototype()
            sectors = dlg.get_sectors()
            offer_comments = dlg.get_offer_comments()
        finally:
            dlg.Destroy()

        # Capturer la sélection avant de basculer sur la nouvelle version
        sel_path = self.editor_panel.get_selection_path()
        tab_idx = self.notebook.GetSelection()

        new_version = self.project.add_version_variant(label, kind, sale_quantities=qtys, annual_volume=volume,
                                                        base_version_index=base_version)
        new_version.phase.label = phase_label
        new_version.phase.tooling_billing = billing
        new_version.is_prototype = prototype
        new_version.sectors = sectors
        new_version.offer_comments = offer_comments
        self.project.switch_to_version(new_version.version_index)
        self._rebuild_version_bar()
        # La nouvelle version est une copie : conserver la sélection courante + l'onglet
        self._reload_all_panels(editor_selection_path=sel_path)
        if tab_idx != wx.NOT_FOUND:
            self.notebook.SetSelection(tab_idx)
        self._dirty = True  # La création d'une version est une modification
        self._update_title()

    def _on_version_context_menu(self, version_index: int):
        """Clic droit sur une version : modifier, dupliquer, supprimer."""
        menu = wx.Menu()
        m_edit = menu.Append(wx.ID_ANY, "Modifier (nom, quantités)…")
        m_dup = menu.Append(wx.ID_ANY, "Dupliquer")
        m_del = menu.Append(wx.ID_ANY, "Supprimer…")
        m_del.Enable(len(self.project.versions) > 1)
        self.Bind(wx.EVT_MENU, lambda e: self._on_edit_version(version_index), m_edit)
        self.Bind(wx.EVT_MENU, lambda e: self._on_duplicate_version(version_index), m_dup)
        self.Bind(wx.EVT_MENU, lambda e: self._on_delete_version(version_index), m_del)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_duplicate_version(self, version_index: int = None):
        """Copie une version (par défaut la courante) et bascule dessus.

        Pas de confirmation : la copie est toujours libre, y compris depuis une version
        figée par une offre (c'est la façon de continuer à modifier une gamme émise).
        """
        if not self.project:
            return
        sel_path = self.editor_panel.get_selection_path()
        tab_idx = self.notebook.GetSelection()
        new_version = self.project.duplicate_version(version_index)
        self.project.switch_to_version(new_version.version_index)
        self._rebuild_version_bar()
        self._reload_all_panels(editor_selection_path=sel_path)
        if tab_idx != wx.NOT_FOUND:
            self.notebook.SetSelection(tab_idx)
        self._mark_dirty()

    def _on_delete_version(self, version_index: int = None):
        """Supprime une version (par défaut la courante), avec avertissement si une offre la fige."""
        if not self.project:
            return
        from domain import offers
        if version_index is None:
            version_index = self.project.current_version_index
        version = self.project.get_version(version_index)
        if version is None:
            return
        if len(self.project.versions) <= 1:
            wx.MessageBox("Impossible de supprimer le seul scénario du projet.",
                          "Supprimer le scénario", wx.OK | wx.ICON_INFORMATION)
            return

        name = version.label.strip() or f"S{version_index}"
        issued = offers.version_offers(self.project.export_history, version_index)
        if issued:
            lines = "\n".join(f"  • {ref}" + (f"  ({n} indices)" if n > 1 else "") for ref, n in issued)
            text = (f"⚠ Le scénario « {name} » est figé par une offre émise :\n\n{lines}\n\n"
                    "La supprimer retire aussi ces offres de l'historique du projet, fichiers XLSX "
                    "embarqués compris. Les devis déjà envoyés au client ne sont pas touchés, mais ils "
                    "ne seront plus retrouvables dans MWQuote.\n\nSupprimer quand même ce scénario ?")
            icon = wx.ICON_WARNING
        else:
            text = f"Supprimer le scénario « {name} » et toute sa gamme ?"
            icon = wx.ICON_QUESTION
        if wx.MessageBox(text, "Supprimer le scénario", wx.YES_NO | wx.NO_DEFAULT | icon) != wx.YES:
            return

        was_current = version_index == self.project.current_version_index
        tab_idx = self.notebook.GetSelection()
        if not self.project.delete_version(version_index):
            return
        self._rebuild_version_bar()
        if was_current:
            self._reload_all_panels()
            if tab_idx != wx.NOT_FOUND:
                self.notebook.SetSelection(tab_idx)
        else:
            self._reload_keeping_selection()
        self.sales_panel.refresh_offers()
        self._mark_dirty()

    def _on_split_version(self, event):
        """Sépare la version courante en un nouveau projet autonome."""
        if not self.project:
            return

        v_idx = self.project.current_version_index
        v_label = next(
            (v.label for v in self.project.versions if v.version_index == v_idx),
            ""
        )
        v_name = v_label.strip() if v_label.strip() else f"S{v_idx}"

        if wx.MessageBox(
            f"Créer un nouveau projet à partir du scénario {v_name} ?\n\n"
            "Le nouveau projet héritera de la référence, du client, de la preview "
            "et des exports de ce scénario.",
            "Séparer le scénario",
            wx.YES_NO | wx.ICON_QUESTION
        ) != wx.YES:
            return

        try:
            new_project = self.project.split_version_to_project(v_idx)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de la séparation : {e}", "Erreur", wx.OK | wx.ICON_ERROR)
            return

        root = self.config.get_quotes_root_folder()
        default_file = ""
        if root:
            try:
                default_file = FileManager.get_mwq_path(
                    root, new_project.mwq_uuid, new_project.reference, new_project.name
                )
            except Exception:
                pass

        with wx.FileDialog(
            self,
            f"Enregistrer le nouveau projet (scénario {v_name})",
            defaultFile=os.path.basename(default_file) if default_file else "",
            defaultDir=os.path.dirname(default_file) if default_file else "",
            wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            save_path = fd.GetPath()

        try:
            PersistenceService.save_project(new_project, save_path)
            self.indexer.index_file(save_path)
            wx.MessageBox(
                f"Scénario {v_name} séparé avec succès !\n{save_path}",
                "Séparation réussie",
                wx.OK | wx.ICON_INFORMATION
            )
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'enregistrement : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    # ------------------------------------------------------------------ #
    # Export XLSX                                                          #
    # ------------------------------------------------------------------ #

    def _on_export_serie_xlsx(self, event=None):
        """Exporte une offre Série (chiffrage gros volumes) depuis l'onglet Production Série."""
        if not self.project:
            return
        if getattr(self.project, 'serie_data', None) is None:
            wx.MessageBox(
                "Ce scénario n'a pas de phase Série.\n"
                "Ajoutez-en une avec « + Phase » (type : Série) avant de générer une offre série.",
                "Pas de phase Série",
                wx.OK | wx.ICON_INFORMATION
            )
            return
        # S'assurer que les données série sont à jour vis-à-vis de la gamme
        try:
            self.project.serie_data.sync_from_project(self.project)
        except Exception:
            pass
        self._on_export_xlsx(serie_offer=True)

    def _on_preview_offer(self, serie_offer=False):
        """Aperçu de l'offre : XLSX brouillon dans un dossier temporaire, ouvert dans Excel.

        Rien n'est enregistré : pas de numéro de devis consommé, pas d'entrée
        d'historique, projet inchangé.
        """
        if not self.project:
            return
        template_path = str(get_template_path())
        if not os.path.exists(template_path):
            wx.MessageBox(f"Le template XLSX est introuvable :\n{template_path}",
                          "Template manquant", wx.OK | wx.ICON_ERROR)
            return
        if serie_offer:
            if self.project.serie_data is None:
                wx.MessageBox("Ce scénario n'a pas de phase Série.", "Pas de phase Série",
                              wx.OK | wx.ICON_INFORMATION)
                return
            self.project.serie_data.sync_from_project(self.project)

        preview_dir = os.path.join(tempfile.gettempdir(), "MWQuote_apercus")
        ref = "".join(c for c in (self.project.reference or "offre") if c.isalnum() or c in "-_") or "offre"
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = "-SERIE" if serie_offer else ""
        output_path = os.path.join(preview_dir, f"BROUILLON-{ref}{suffix}-{stamp}.xlsx")
        try:
            self.export_service.export_excel(self.project, template_path, output_path,
                                             serie_offer=serie_offer, draft=True)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de la génération de l'aperçu :\n{e}", "Erreur", wx.OK | wx.ICON_ERROR)
            return
        try:
            os.startfile(output_path)
        except Exception:
            wx.MessageBox(f"Aperçu généré :\n{output_path}", "Aperçu de l'offre", wx.OK | wx.ICON_INFORMATION)

    def _on_export_xlsx(self, event=None, serie_offer=False, revise_ref=None):
        """Exporte la version courante du projet en devis XLSX (offre standard ou série).

        revise_ref : numéro de devis d'une offre existante → nouvel indice de cette offre.
        """
        if not self.project:
            return
        self.project_panel.flush()          # bloc-notes : l'export enregistre le projet, notes comprises

        # Vérifier le template
        template_path = str(get_template_path())
        if not os.path.exists(template_path):
            wx.MessageBox(
                f"Le template XLSX est introuvable :\n{template_path}\n\n"
                "Vérifiez que TEMPLATE.xlsx est présent dans le dossier 'assets'.",
                "Template manquant",
                wx.OK | wx.ICON_ERROR
            )
            return

        offer_kind = "Série" if serie_offer else "standard"

        # Le numéro de devis et l'historique d'export vivent dans le fichier .mwq :
        # on s'assure qu'il existe AVANT de consommer un numéro, sinon l'offre émise
        # n'aurait aucune trace dans la base (projet jamais enregistré).
        if not self.current_path and not self._save_project(allow_dialog=True):
            return

        # Référence devis : nouveau numéro, ou numéro existant pour un nouvel indice
        from domain import offers
        was_frozen = self.project.is_version_frozen()
        if revise_ref:
            reference = revise_ref
            revision = offers.next_revision(self.project.export_history, revise_ref)
        else:
            reference = self.export_service.get_devis_reference(project=self.project)
            revision = offers.FIRST_REVISION
        default_filename = self.export_service.get_default_filename(
            self.project, devis_ref=reference, revision=revision
        )
        if serie_offer:
            base, ext = os.path.splitext(default_filename)
            default_filename = f"{base}-SERIE{ext}"

        # Demander le chemin de sortie
        with wx.FileDialog(
            self,
            f"Enregistrer l'offre {offer_kind} XLSX",
            defaultDir=os.path.expanduser("~\\Desktop"),
            defaultFile=default_filename,
            wildcard="Fichiers Excel (*.xlsx)|*.xlsx",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            output_path = fd.GetPath()

        progress = wx.ProgressDialog(
            f"Création de l'offre {offer_kind} XLSX",
            "Génération du document à partir du template...",
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        try:
            self.export_service.export_excel(
                self.project,
                template_path,
                output_path,
                project_save_path=self.current_path,
                devis_ref=reference,
                serie_offer=serie_offer,
                revision=revision
            )
            progress.Destroy()

            # L'export a enregistré le projet (historique d'offres inclus) : on réindexe
            # pour que la liste voie la nouvelle offre, et il n'y a plus rien à enregistrer.
            try:
                self.indexer.index_file(self.current_path)
            except Exception:
                import logging
                logging.getLogger(__name__).warning("Réindexation après export impossible", exc_info=True)
            self._dirty = False
            self._update_title()

            # Arbre d'offres à jour + gel de la gamme
            self._after_offer_issued(was_frozen)

            # Ouvrir le fichier automatiquement
            try:
                os.startfile(output_path)
            except Exception:
                pass

        except PermissionError as e:
            progress.Destroy()
            wx.MessageBox(
                f"Impossible d'enregistrer le fichier.\n"
                "Vérifiez qu'il n'est pas déjà ouvert dans Excel.\n\n"
                f"Détail : {e}",
                "Erreur d'accès",
                wx.OK | wx.ICON_ERROR
            )
        except Exception as e:
            progress.Destroy()
            wx.MessageBox(
                f"Erreur lors de la création de l'offre :\n{e}",
                "Erreur",
                wx.OK | wx.ICON_ERROR
            )

    def _on_export_fabrication_quality(self, event=None):
        """Exporte le XLSX Fabrication/Qualité (gamme, temps, commentaires).

        Destination : <dossier projet>\\PROCESS si un dossier projet est défini,
        sinon on demande l'emplacement.
        """
        if not self.project:
            return

        # Nom de fichier proposé
        ref = (self.project.reference or self.project.name or "Projet").strip()
        safe_ref = "".join(c if c.isalnum() or c in " -_" else "_" for c in ref).strip() or "Projet"
        filename = f"{safe_ref}_Fabrication_Qualite.xlsx"

        output_path = None
        project_folder = getattr(self.project, 'project_folder', "") or ""
        if project_folder:
            process_dir = ProjectFolderService.process_dir(project_folder)
            try:
                os.makedirs(process_dir, exist_ok=True)
                output_path = os.path.join(process_dir, filename)
            except Exception as e:
                wx.MessageBox(
                    f"Impossible de créer le dossier PROCESS :\n{process_dir}\n\n{e}\n\n"
                    "Choisissez un emplacement manuellement.",
                    "Dossier PROCESS", wx.OK | wx.ICON_WARNING
                )
                output_path = None

        if not output_path:
            with wx.FileDialog(
                self, "Exporter Fabrication/Qualité",
                defaultDir=os.path.expanduser("~\\Desktop"),
                defaultFile=filename,
                wildcard="Fichiers Excel (*.xlsx)|*.xlsx",
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
            ) as fd:
                if fd.ShowModal() == wx.ID_CANCEL:
                    return
                output_path = fd.GetPath()

        progress = wx.ProgressDialog(
            "Export Fabrication/Qualité", "Génération du document...",
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE, parent=self
        )
        try:
            self.export_service.export_fabrication_quality(self.project, output_path)
        except Exception as e:
            wx.MessageBox(
                f"Erreur lors de l'export Fabrication/Qualité :\n{e}",
                "Erreur", wx.OK | wx.ICON_ERROR
            )
            return
        finally:
            progress.Destroy()

        try:
            os.startfile(output_path)
        except Exception:
            pass

    def _update_title(self):
        """Met à jour le titre de la fenêtre avec la référence ou le nom du projet."""
        if not self.project:
            self.SetTitle("MWQuote")
            return
        display_name = self.project.display_name
        v_idx = self.project.current_version_index
        phase = self.project.current_phase.display_label
        dirty_marker = " ●" if self._dirty else ""
        self.SetTitle(f"MWQuote - {display_name}  [S{v_idx} · {phase}]{dirty_marker}")

    def _on_operation_updated(self, operation, reload_header=False):
        """Appelé quand une opération est modifiée.

        Args:
            operation: L'opération modifiée (peut être None pour refresh sans contexte)
            reload_header: Si True, recharge aussi le project_panel (pour ajout/suppression d'opérations)
        """
        # Recharger le header seulement si explicitement demandé
        if reload_header:
            self.project_panel.load_project(self.project)

        # Rafraîchir tous les panels de données
        self._refresh_all_data_panels()
        self._refresh_phase_warnings()
        self._mark_dirty()

        self._mark_dirty()

    def _on_serie_updated(self):
        """Appelé quand les données Série sont modifiées."""
        self._rebuild_version_bar()
        # Le Tarif de Vente lit le prix série en direct : le rafraîchir pour que
        # CAPEX / outillages / achats / setup y soient pris en compte aussitôt.
        self.sales_panel.refresh_data()
        self._mark_dirty()

    def _refresh_all_data_panels(self):
        """Rafraîchit tous les panels de données (grid, graphiques, etc.)."""
        self.sales_panel.refresh_data()
        self.serie_panel.refresh_data()

    def _on_new(self, event):
        """Réinitialise avec un nouveau projet"""
        if not self._confirm_discard_or_save():
            return
        new_project = Project(name="", reference="", client="", mwq_uuid=FileManager.generate_uuid())
        self._prompt_first_phase(new_project)
        self._update_app_with_project(new_project)
        self.current_path = None
        self._dirty = False
        self._update_title()

    def _on_new_quote_opened(self):
        """Fenêtre d'une nouvelle quote ouverte : popup de la première phase."""
        if not self.project:
            return
        self._prompt_first_phase(self.project)
        self._reload_keeping_selection()
        self._update_title()

    def _prompt_first_phase(self, project):
        """Première version d'une nouvelle quote : type de calcul + quantités (ou volume).

        Annulation : la version 1 garde sa configuration par défaut (Taux horaire,
        quantités standard).
        """
        from ui.dialogs.phase_dialog import PhaseDialog
        dlg = PhaseDialog(self, title="Premier scénario du projet")
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            kind = dlg.get_kind()
            label = dlg.get_label()
            phase_label = dlg.get_phase_label()
            qtys = dlg.get_quantities()
            volume = dlg.get_annual_volume()
            billing = dlg.get_tooling_billing()
            prototype = dlg.get_prototype()
            sectors = dlg.get_sectors()
            offer_comments = dlg.get_offer_comments()
        finally:
            dlg.Destroy()

        version = project.current_version
        version.configure(kind, sale_quantities=qtys, annual_volume=volume)
        version.is_prototype = prototype
        version.sectors = sectors
        version.offer_comments = offer_comments
        version.label = label
        version.phase.label = phase_label
        version.phase.tooling_billing = billing

    def _on_open(self, event):
        """Ouvre un projet depuis un fichier"""
        if not self._confirm_discard_or_save():
            return
        with wx.FileDialog(self, "Ouvrir un projet", wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                          style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            path = fileDialog.GetPath()
            try:
                project = PersistenceService.load_project(path)
                self.current_path = path
                self._update_app_with_project(project)
                self._dirty = False
                self._update_title()
            except Exception as e:
                wx.MessageBox(f"Erreur lors du chargement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_duplicate(self, event):
        """Duplique le projet actuel"""
        if not self.current_path:
            wx.MessageBox("Veuillez d'abord ouvrir un projet.", "Information", wx.OK | wx.ICON_INFORMATION)
            return

        base, ext = os.path.splitext(self.current_path)
        default_name = os.path.basename(base) + "_copie" + ext

        with wx.FileDialog(self, "Dupliquer le projet", 
                          defaultFile=default_name,
                          wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                          style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            path = fileDialog.GetPath()
            try:
                # Use clone to reset milestones
                cloned_project = self.project.clone()
                PersistenceService.save_project(cloned_project, path)
                # Auto-index in DB
                self.indexer.index_file(path)
                wx.MessageBox(
                    "Projet dupliqué avec succès !",
                    "Information",
                    wx.OK | wx.ICON_INFORMATION
                )
            except Exception as e:
                wx.MessageBox(f"Erreur lors de la duplication : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_close(self, event):
        """Appelé à la fermeture de la fenêtre principale"""
        self.project_panel.flush()          # bloc-notes : une saisie récente doit compter comme modification
        # Cleanup temporary files created during document viewing
        if hasattr(self.project_panel, 'doc_list') and hasattr(self.project_panel.doc_list, 'cleanup_temp_files'):
            self.project_panel.doc_list.cleanup_temp_files()
        
        if self._dirty:
            res = wx.MessageBox(
                "Des modifications n'ont pas été enregistrées.\nSouhaitez-vous enregistrer avant de fermer ?",
                "Modifications non enregistrées",
                wx.YES_NO | wx.CANCEL | wx.ICON_WARNING
            )
            if res == wx.CANCEL:
                event.Veto()
                return
            if res == wx.YES:
                if not self._save_project(allow_dialog=True):
                    event.Veto()
                    return
        clear_logs_directory()
        # La fermeture est acquise (ni annulée, ni refusée) : on prévient l'appelant
        # (fenêtre liste) avec le chemin du projet, une fois la sauvegarde faite.
        closed_path = self.current_path
        callback = self.on_closed
        self.Destroy()
        if callback:
            wx.CallAfter(callback, closed_path)

    def _confirm_discard_or_save(self) -> bool:
        """Propose l'enregistrement si des modifications sont en attente.

        Returns True si on peut continuer (sauvegardé ou abandonné),
        False si l'utilisateur annule.
        """
        self.project_panel.flush()          # bloc-notes : saisie récente pas encore signalée
        if not self._dirty:
            return True
        res = wx.MessageBox(
            "Des modifications n'ont pas été enregistrées.\nSouhaitez-vous les enregistrer ?",
            "Modifications non enregistrées",
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
        )
        if res == wx.CANCEL:
            return False
        if res == wx.YES:
            return self._save_project(allow_dialog=True)
        # NO → on abandonne les modifications
        return True

    def _mark_dirty(self):
        self._dirty = True
        self._update_title()

    def _save_project(self, allow_dialog: bool = True) -> bool:
        """Enregistre le projet.

        Si aucun chemin connu, tente de déduire le chemin depuis le dossier racine.
        Si toujours absent et allow_dialog=True, ouvre un FileDialog.
        Retourne True si sauvegardé avec succès.
        """
        if not self.project:
            return False
        self.project_panel.flush()          # bloc-notes : la dernière saisie part avec le projet

        if not self.current_path:
            # Tenter de déduire le chemin depuis le dossier racine configuré
            root = self.config.get_quotes_root_folder()
            if root:
                mwq_uuid = self.project.mwq_uuid or FileManager.generate_uuid()
                self.project.mwq_uuid = mwq_uuid
                try:
                    self.current_path = FileManager.get_mwq_path(
                        root, mwq_uuid, self.project.reference, self.project.name
                    )
                except Exception:
                    self.current_path = None

            if not self.current_path:
                if not allow_dialog:
                    return False
                with wx.FileDialog(
                    self, "Enregistrer le projet",
                    wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                    style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
                ) as fd:
                    if fd.ShowModal() == wx.ID_CANCEL:
                        return False
                    self.current_path = fd.GetPath()

        try:
            PersistenceService.save_project(self.project, self.current_path)
            self.indexer.index_file(self.current_path)
            self.template_manager.record_project_template_usage(self.project)
            self._dirty = False
            self._update_title()
            return True
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'enregistrement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)
            return False

    def _on_save(self, event):
        self._save_project(allow_dialog=True)

    def _on_save_as(self, event):
        old_path = self.current_path
        self.current_path = None
        if not self._save_project(allow_dialog=True):
            self.current_path = old_path
