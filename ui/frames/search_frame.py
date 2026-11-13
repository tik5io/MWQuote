import wx
import wx.lib.scrolledpanel as scrolled
import os
import sys
import shutil
import io
import json
import datetime as dt_module
from collections import defaultdict
from datetime import date, datetime
from infrastructure.database import Database
from infrastructure.indexer import Indexer
from infrastructure.persistence import PersistenceService
from infrastructure.configuration import ConfigurationService
from infrastructure.migration_service import MigrationService
from infrastructure.file_manager import FileManager
from infrastructure.export_service import ExportService
from infrastructure.template_manager import TemplateManager
from infrastructure.analytics_service import AnalyticsService
from infrastructure.logging_service import get_module_logger
from ui.panels.search_project_details_panel import ProjectDetailsPanel
from ui.panels.comparison_panel import ComparisonPanel
from ui.frames.business_dashboard_frame import BusinessDashboardFrame
import QuoteEditor_app
from ui.components.theme import *  # noqa: F401,F403  (palette, font, FlatButton)
from ui.components.theme import font as _font
from core.app_icon import get_icon_path, load_icon_from_sheet, get_template_path

logger = get_module_logger("SearchFrame", "search_frame.log")

MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
             "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
DAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def _fmt_datetime(ts):
    s = str(ts or "")
    try:
        return datetime.fromisoformat(s[:19]).strftime("%d/%m/%Y  %H:%M")
    except Exception:
        return s[:16]


def _fmt_date(ts):
    s = str(ts or "")
    try:
        return datetime.fromisoformat(s[:10]).strftime("%d/%m/%Y")
    except Exception:
        return s


class TimelinePanel(scrolled.ScrolledPanel):
    """Chronological timeline view of project activity."""

    EVENT_COLORS = {
        "modified": UI_ACCENT,
    }
    EVENT_ICONS = {
        "modified": "●",
    }
    EVENT_LABELS = {
        "modified": "Modifié",
    }

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundColour(UI_BG)
        self.on_item_selected = None
        self.on_item_activated = None
        self._selected_card = None
        self._main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._main_sizer)
        self.SetupScrolling(scroll_x=False)

    def load_events(self, db_rows):
        """Rebuild the timeline from a list of DB project rows."""
        self._main_sizer.Clear(True)
        self._selected_card = None

        events = []
        today = date.today()

        for p in db_rows:
            # Last-modified event (has timestamp with time)
            ts = str(p.get('last_modified') or '')
            if ts:
                try:
                    ev_dt = datetime.fromisoformat(ts[:19])
                    events.append({"datetime": ev_dt, "type": "modified", "project": p, "detail": ev_dt.strftime("%H:%M")})
                except Exception:
                    pass

        events.sort(key=lambda e: e["datetime"], reverse=True)

        day_groups = defaultdict(list)
        for ev in events:
            day_groups[ev["datetime"].date()].append(ev)

        self.Freeze()
        try:
            # Destroy all existing child windows cleanly
            for child in list(self.GetChildren()):
                child.Destroy()
            self._main_sizer = wx.BoxSizer(wx.VERTICAL)

            if not events:
                placeholder = wx.StaticText(self, label="Aucune activité enregistrée.")
                placeholder.SetForegroundColour(wx.Colour(150, 150, 150))
                self._main_sizer.Add(placeholder, 0, wx.ALL, 20)
            else:
                for day in sorted(day_groups.keys(), reverse=True):
                    self._add_day_section(day, day_groups[day], today)

            self._main_sizer.AddSpacer(20)
            self.SetSizer(self._main_sizer, deleteOld=True)
            self.SetupScrolling(scroll_x=False)
            self.Layout()
            self.Scroll(0, 0)
        finally:
            self.Thaw()

    def _add_day_section(self, day, events, today):
        # Day header
        header = wx.Panel(self)
        header.SetBackgroundColour(UI_BG)
        h_sizer = wx.BoxSizer(wx.HORIZONTAL)
        label_text = self._format_day(day, today)
        lbl = wx.StaticText(header, label=label_text.upper())
        lbl.SetFont(_font(8, bold=True))
        lbl.SetForegroundColour(UI_MUTED)
        h_sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.TOP | wx.BOTTOM, 6)
        header.SetSizer(h_sizer)
        self._main_sizer.Add(header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 14)

        for ev in events:
            card = self._make_card(ev)
            self._main_sizer.Add(card, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        self._main_sizer.AddSpacer(4)

    def _format_day(self, d, today):
        if d == today:
            return f"Aujourd'hui  —  {d.day} {MONTHS_FR[d.month - 1]} {d.year}"
        if d == today - dt_module.timedelta(days=1):
            return f"Hier  —  {d.day} {MONTHS_FR[d.month - 1]} {d.year}"
        return f"{DAYS_FR[d.weekday()]} {d.day} {MONTHS_FR[d.month - 1]} {d.year}"

    def _make_card(self, ev):
        p = ev["project"]
        ev_type = ev["type"]
        color = self.EVENT_COLORS[ev_type]
        icon = self.EVENT_ICONS[ev_type]
        label = self.EVENT_LABELS[ev_type]
        detail = ev["detail"]

        card = wx.Panel(self, style=wx.BORDER_NONE)
        card.SetBackgroundColour(wx.Colour(255, 255, 255))

        outer = wx.BoxSizer(wx.HORIZONTAL)

        # Left color stripe
        stripe = wx.Panel(card, size=(4, -1))
        stripe.SetBackgroundColour(color)
        outer.Add(stripe, 0, wx.EXPAND)

        # Card content
        content = wx.BoxSizer(wx.VERTICAL)

        # Row 1: event type + reference + client + status badge
        row1 = wx.BoxSizer(wx.HORIZONTAL)

        type_lbl = wx.StaticText(card, label=f"{icon} {label}")
        type_lbl.SetFont(_font(9, bold=True))
        type_lbl.SetForegroundColour(color)
        row1.Add(type_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)

        sep_lbl = wx.StaticText(card, label="  |  ")
        sep_lbl.SetForegroundColour(wx.Colour(180, 180, 180))
        row1.Add(sep_lbl, 0, wx.ALIGN_CENTER_VERTICAL)

        ref_text = f"{p.get('reference', '—')}   {p.get('client', '')}"
        ref_lbl = wx.StaticText(card, label=ref_text)
        ref_lbl.SetFont(_font(10))
        ref_lbl.SetForegroundColour(UI_TEXT)
        row1.Add(ref_lbl, 1, wx.ALIGN_CENTER_VERTICAL)

        content.Add(row1, 0, wx.EXPAND | wx.TOP, 8)

        # Row 2: time detail (for modified and export)
        if ev_type in ("modified", "export") and detail:
            detail_lbl = wx.StaticText(card, label=f"        {detail}")
            detail_lbl.SetForegroundColour(wx.Colour(120, 120, 120))
            detail_lbl.SetFont(_font(8))
            content.Add(detail_lbl, 0, wx.BOTTOM, 8)
        else:
            content.AddSpacer(4)

        outer.Add(content, 1, wx.EXPAND)
        card.SetSizer(outer)

        # Bind click/double-click on all child widgets
        all_widgets = [card, stripe, type_lbl, sep_lbl, ref_lbl]

        def on_click(event, p_data=p, c=card):
            self._set_selected(c)
            if self.on_item_selected:
                self.on_item_selected(p_data)

        def on_dclick(event, p_data=p):
            if self.on_item_activated:
                self.on_item_activated(p_data)

        for w in all_widgets:
            w.Bind(wx.EVT_LEFT_UP, on_click)
            w.Bind(wx.EVT_LEFT_DCLICK, on_dclick)

        return card

    def _set_selected(self, card):
        if self._selected_card and self._selected_card is not card:
            try:
                self._selected_card.SetBackgroundColour(wx.Colour(255, 255, 255))
                self._selected_card.Refresh()
            except Exception:
                pass
        self._selected_card = card
        card.SetBackgroundColour(wx.Colour(226, 236, 253))
        card.Refresh()


class SearchFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="MWProjet", size=(1280, 820))

        self.db = Database()
        self.indexer = Indexer(self.db)
        self.config = ConfigurationService.get_instance()
        self.migration_service = MigrationService(self.db)
        self.export_service = ExportService(db=self.db)
        self.template_manager = TemplateManager(self.db)
        self.analytics_service = AnalyticsService(self.db)
        
        self._start_weekly_backup()

        self._build_ui()
        self._build_menu()
        self._set_app_icon()
        # Sorting state (must be before _refresh_list)
        self.sort_col = "last_modified"
        self.sort_ascending = False
        self._timeline_mode = False

        self._refresh_list()
        # Base indexée avant les colonnes « dernière offre » : on les complète en arrière-plan.
        self.indexer.backfill_offer_index(
            completion_callback=lambda n: wx.CallAfter(self._after_offer_backfill, n))

        self.Centre()
        self.Show()
        wx.CallAfter(self._init_sash)
        
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)

    def _after_offer_backfill(self, count):
        if self and count:
            self._refresh_list()

    def _init_sash(self):
        """Position initiale du séparateur : ~58 % liste / 42 % détails (la taille réelle n'est connue qu'après affichage)."""
        try:
            self.splitter.SetSashPosition(int(self.splitter.GetSize().GetWidth() * 0.64))
        except Exception:
            pass

    def _set_app_icon(self):
        try:
            icon_path = get_icon_path()
            if icon_path.exists():
                self.SetIcon(wx.Icon(str(icon_path), wx.BITMAP_TYPE_ICO))
        except Exception:
            pass

    def _backup_service(self, backup_dir=None):
        """Service de sauvegarde ; `backup_dir` surcharge le dossier configuré (fenêtre Réglages)."""
        from infrastructure.backup_service import BackupService
        return BackupService(
            db_path=self.db.get_db_path(),
            projects_root=self.config.get_quotes_root_folder(),
            config_path=self.config.config_path,
            backup_dir=backup_dir or self.config.get_backup_folder(),
        )

    def _start_weekly_backup(self):
        """Sauvegarde hebdomadaire automatique (base + projets), en tâche de fond, sans popup."""
        try:
            self._backup_service().start_background()
        except Exception:
            logger.exception("Démarrage de la sauvegarde automatique impossible")

    def _on_backup_now(self, backup_dir=None, on_done=None):
        """Sauvegarde immédiate à la demande (action explicite : un message de fin est affiché)."""
        svc = self._backup_service(backup_dir)

        def _done(path, error):
            def _show():
                if on_done:
                    on_done()
                if error:
                    wx.MessageBox(f"La sauvegarde a échoué :\n{error}", "Sauvegarde", wx.OK | wx.ICON_ERROR)
                else:
                    wx.MessageBox(f"Sauvegarde créée :\n{path}", "Sauvegarde", wx.OK | wx.ICON_INFORMATION)
            wx.CallAfter(_show)

        def _work():
            try:
                path = svc.create_backup()
                svc.prune()
                _done(path, None)
            except Exception as exc:
                logger.exception("Sauvegarde manuelle échouée")
                _done(None, exc)

        import threading
        threading.Thread(target=_work, name="mwquote-backup-now", daemon=True).start()

    def _on_activate(self, event):
        """Refresh list when window gets focus (return from editor)"""
        if event.GetActive():
            self._refresh_list()
        event.Skip()

    def _build_ui(self):
        self._mode_filter = "all"
        self._search_timer = None

        main_panel = wx.Panel(self)
        main_panel.SetBackgroundColour(UI_BG)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # --- Bandeau d'en-tête : identité + indicateurs + action principale ---
        header = wx.Panel(main_panel)
        header.SetBackgroundColour(UI_NAVY)
        h = wx.BoxSizer(wx.HORIZONTAL)

        titles = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(header, label="MWProjet")
        title.SetFont(_font(18, bold=True))
        title.SetForegroundColour(wx.WHITE)
        subtitle = wx.StaticText(header, label="Projets, gammes et offres")
        subtitle.SetFont(_font(9))
        subtitle.SetForegroundColour(UI_NAVY_MUTED)
        titles.Add(title, 0)
        titles.Add(subtitle, 0, wx.TOP, 1)
        h.Add(titles, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.TOP | wx.BOTTOM, 20)

        h.AddStretchSpacer(1)

        self.kpi_labels = {}
        for key, caption in (("total", "PROJETS"), ("serie", "SÉRIE"), ("proto", "PROTOTYPE")):
            box = wx.BoxSizer(wx.VERTICAL)
            value = wx.StaticText(header, label="0", style=wx.ALIGN_CENTRE_HORIZONTAL)
            value.SetFont(_font(17, bold=True))
            value.SetForegroundColour(wx.WHITE)
            cap = wx.StaticText(header, label=caption, style=wx.ALIGN_CENTRE_HORIZONTAL)
            cap.SetFont(_font(7, bold=True))
            cap.SetForegroundColour(UI_NAVY_MUTED)
            box.Add(value, 0, wx.EXPAND)
            box.Add(cap, 0, wx.EXPAND)
            self.kpi_labels[key] = value
            h.Add(box, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 28)

        new_btn = FlatButton(header, "+  Nouveau projet", kind="primary")
        new_btn.Bind(wx.EVT_BUTTON, self._on_new_quote)
        h.Add(new_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 20)
        header.SetSizer(h)
        vbox.Add(header, 0, wx.EXPAND)

        # --- Barre d'outils : recherche, filtres, export, vue ---
        bar = wx.Panel(main_panel)
        bar.SetBackgroundColour(UI_BG)
        t = wx.BoxSizer(wx.HORIZONTAL)

        self.search_global = wx.SearchCtrl(bar, size=(300, 30), style=wx.TE_PROCESS_ENTER)
        self.search_global.SetHint("Référence, client, nom…")
        self.search_global.ShowCancelButton(True)
        self.search_global.SetFont(_font(10))
        self.search_global.Bind(wx.EVT_TEXT, self._on_search_text)
        self.search_global.Bind(wx.EVT_SEARCH_CANCEL, self._on_reset)
        t.Add(self.search_global, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.TOP | wx.BOTTOM, 14)

        self.chips = {}
        for key, label in (("all", "Tous"), ("serie", "Série"), ("proto", "Prototype")):
            chip = FlatButton(bar, label, kind="chip")
            chip.SetActive(key == "all")
            chip.Bind(wx.EVT_BUTTON, lambda e, k=key: self._set_mode_filter(k))
            self.chips[key] = chip
            t.Add(chip, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 16 if key == "all" else 6)

        t.AddStretchSpacer(1)

        self.select_all_cb = wx.CheckBox(bar, label="Tout sélectionner")
        self.select_all_cb.SetFont(_font(9))
        self.select_all_cb.SetForegroundColour(UI_MUTED)
        self.select_all_cb.SetToolTip("Cocher / décocher tous les projets affichés (filtre en cours)")
        self.select_all_cb.Bind(wx.EVT_CHECKBOX, self._on_master_check)
        t.Add(self.select_all_cb, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        self.synth_export_btn = FlatButton(bar, "Exporter synthèse Excel", kind="secondary")
        self.synth_export_btn.SetToolTip("Générer un Excel unique de synthèse pour les projets cochés")
        self.synth_export_btn.Bind(wx.EVT_BUTTON, self._on_export_synthesis)
        self.synth_export_btn.Disable()
        t.Add(self.synth_export_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        self.view_toggle_btn = FlatButton(bar, "Chronologie", kind="secondary")
        self.view_toggle_btn.SetToolTip("Basculer entre vue liste et vue chronologique")
        self.view_toggle_btn.Bind(wx.EVT_BUTTON, self._on_toggle_view)
        t.Add(self.view_toggle_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)

        bar.SetSizer(t)
        vbox.Add(bar, 0, wx.EXPAND)

        # --- Séparateur fin + zone principale (liste / détails) ---
        sep = wx.Panel(main_panel, size=(-1, 1))
        sep.SetBackgroundColour(UI_BORDER)
        vbox.Add(sep, 0, wx.EXPAND)

        self.splitter = wx.SplitterWindow(main_panel, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.splitter.SetSashGravity(0.5)
        self.splitter.SetBackgroundColour(UI_BORDER)

        self.left_container = wx.Panel(self.splitter)
        self.left_container.SetBackgroundColour(wx.WHITE)
        self.left_sizer = wx.BoxSizer(wx.VERTICAL)

        self.list_ctrl = wx.ListCtrl(self.left_container, style=wx.LC_REPORT | wx.BORDER_NONE)
        self.list_ctrl.SetFont(_font(10))
        self.list_ctrl.SetBackgroundColour(wx.WHITE)
        self.list_ctrl.SetTextColour(UI_TEXT)
        # Image list factice : impose une hauteur de ligne plus aérée.
        row_il = wx.ImageList(1, 32)
        spacer = wx.Bitmap(1, 32)
        _dc = wx.MemoryDC(spacer)
        _dc.SetBackground(wx.Brush(wx.WHITE))
        _dc.Clear()
        _dc.SelectObject(wx.NullBitmap)
        row_il.Add(spacer)
        self.list_ctrl.AssignImageList(row_il, wx.IMAGE_LIST_SMALL)
        # Colonnes utiles au quotidien : qui, quoi, où en est l'offre.
        self.list_ctrl.InsertColumn(0, "Référence", width=190)
        self.list_ctrl.InsertColumn(1, "Client", width=170)
        self.list_ctrl.InsertColumn(2, "Statut", width=95)
        self.list_ctrl.InsertColumn(3, "Mode", width=125)
        self.list_ctrl.InsertColumn(4, "Dernière offre", width=110)

        try:
            self.list_ctrl.EnableCheckBoxes(True)
            self.list_ctrl.Bind(wx.EVT_LIST_ITEM_CHECKED, self._on_item_checked)
            self.list_ctrl.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._on_item_checked)
        except AttributeError:
            logger.warning("EnableCheckBoxes non disponible (wxPython < 4.1)")

        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_item_selected)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_item_activated)
        self.list_ctrl.Bind(wx.EVT_LIST_COL_CLICK, self._on_col_click)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_list_right_click)
        self.list_ctrl.Bind(wx.EVT_RIGHT_UP, self._on_list_right_click)

        self.timeline_panel = TimelinePanel(self.left_container)
        self.timeline_panel.on_item_selected = self._on_timeline_item_selected
        self.timeline_panel.on_item_activated = self._on_timeline_item_activated
        self.timeline_panel.Hide()

        # État vide (aucun résultat)
        self.empty_label = wx.StaticText(
            self.left_container, label="Aucun projet à afficher.\nModifiez la recherche ou le filtre.",
            style=wx.ALIGN_CENTRE_HORIZONTAL)
        self.empty_label.SetFont(_font(11))
        self.empty_label.SetForegroundColour(UI_MUTED)
        self.empty_label.Hide()

        self.left_sizer.Add(self.list_ctrl, 1, wx.EXPAND)
        self.left_sizer.Add(self.timeline_panel, 1, wx.EXPAND)
        self.left_sizer.Add(self.empty_label, 0, wx.EXPAND | wx.ALL, 24)
        self.left_container.SetSizer(self.left_sizer)

        self.right_container = wx.Panel(self.splitter)
        self.right_container.SetBackgroundColour(wx.WHITE)
        self.right_sizer = wx.BoxSizer(wx.VERTICAL)

        self.details_panel = ProjectDetailsPanel(self.right_container)
        self.comparison_panel = ComparisonPanel(self.right_container)

        self.right_sizer.Add(self.details_panel, 1, wx.EXPAND)
        self.right_sizer.Add(self.comparison_panel, 1, wx.EXPAND)
        self.comparison_panel.Hide()

        self.right_container.SetSizer(self.right_sizer)

        self.splitter.SplitVertically(self.left_container, self.right_container, 700)
        self.splitter.SetMinimumPaneSize(100)

        vbox.Add(self.splitter, 1, wx.EXPAND)
        main_panel.SetSizer(vbox)

        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(main_panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        self.CreateStatusBar()
        self.SetStatusText("Prêt")

        self.search_global.Bind(wx.EVT_TEXT_ENTER, self._on_search)

    # ------------------------------------------------------------------ #
    # Recherche en direct + filtres de mode                                 #
    # ------------------------------------------------------------------ #
    def _on_search_text(self, event):
        """Recherche au fil de la frappe (temporisée pour ne pas relancer la requête à chaque touche)."""
        if self._search_timer is not None:
            self._search_timer.Stop()
        self._search_timer = wx.CallLater(250, self._on_search, None)
        event.Skip()

    def _set_mode_filter(self, key):
        self._mode_filter = key
        for k, chip in self.chips.items():
            chip.SetActive(k == key)
        self._refresh_list()

    def _update_kpis(self, results):
        n_serie = sum(1 for p in results if p.get('has_serie'))
        n_proto = sum(1 for p in results if p.get('is_prototype'))
        for key, val in (("total", len(results)), ("serie", n_serie), ("proto", n_proto)):
            self.kpi_labels[key].SetLabel(str(val))
        self.kpi_labels["total"].GetParent().Layout()

    def _build_menu(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        business_menu = wx.Menu()

        m_new = file_menu.Append(wx.ID_NEW, "&Nouveau projet\tCtrl+N", "Créer un nouveau projet")
        m_open = file_menu.Append(wx.ID_OPEN, "&Ouvrir...\tCtrl+O", "Ouvrir un fichier .mwq")
        file_menu.AppendSeparator()
        m_settings = file_menu.Append(wx.ID_PREFERENCES, "&Réglages...\tCtrl+,",
                                      "Dossiers, sauvegarde : tous les paramètres de l'application")
        file_menu.AppendSeparator()
        m_exit = file_menu.Append(wx.ID_EXIT, "Quitter", "Quitter l'application")

        menubar.Append(file_menu, "&Fichier")
        m_business_dashboard = business_menu.Append(wx.ID_ANY, "Dashboard Business", "Ouvrir le dashboard analytics")
        menubar.Append(business_menu, "&Business")
        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self._on_new_quote, m_new)
        self.Bind(wx.EVT_MENU, self._on_open_file, m_open)
        self.Bind(wx.EVT_MENU, self._on_settings, m_settings)
        self.Bind(wx.EVT_MENU, self._on_open_business_dashboard, m_business_dashboard)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), m_exit)

    def _on_settings(self, event):
        """Fenêtre Réglages : point d'entrée unique des paramètres (dossiers, sauvegarde)."""
        from ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self, self.config, self._backup_service,
                             on_backup_now=self._on_backup_now,
                             on_restore=self._on_restore_database)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            values = dlg.get_values()
        finally:
            dlg.Destroy()

        cfg = self.config
        if values["series_dir"] and values["series_dir"] != cfg.get_series_root_folder():
            cfg.set_series_root_folder(values["series_dir"])
        if values["template_name"] != cfg.get_empty_project_name():
            cfg.set_empty_project_name(values["template_name"])
        if values["backup_dir"] != cfg.get_backup_folder():
            cfg.set_backup_folder(values["backup_dir"])
        if values["projects_dir"] and values["projects_dir"] != (cfg.get_quotes_root_folder() or ""):
            self._apply_projects_root(values["projects_dir"])

    def _apply_projects_root(self, new_folder: str):
        """Nouveau dossier des projets : propose de migrer les fichiers existants, sinon scanne le dossier."""
        old_folder = self.config.get_quotes_root_folder()
        self.config.set_quotes_root_folder(new_folder)
        if old_folder and old_folder != new_folder and os.path.exists(old_folder):
            msg = (f"Ancien dossier : {old_folder}\n"
                   f"Nouveau dossier : {new_folder}\n\n"
                   "Migrer les fichiers existants vers le nouveau dossier ?\n\n"
                   "Les fichiers seront copiés, renommés avec un UUID si nécessaire, et l'index mis à jour.")
            if wx.MessageBox(msg, "Migration des fichiers", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                self._do_auto_migrate(old_folder, new_folder)
                return
        self._do_index(new_folder, migrate=False)

    def _on_open_business_dashboard(self, event):
        frame = BusinessDashboardFrame(self, self.analytics_service)
        frame.Show()

    def _on_new_quote(self, event):
        """Créer une nouvelle quote et ouvrir l'éditeur (modal)"""
        QuoteEditor_app.open_new_quote(parent_frame=self)

    def _on_open_file(self, event):
        """Ouvrir un fichier .mwq directement"""
        with wx.FileDialog(self, "Ouvrir un projet", wildcard="Fichiers MWProjet (*.mwq)|*.mwq",
                          style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            path = fileDialog.GetPath()
            try:
                QuoteEditor_app.open_quote_from_file(path, parent_frame=self, parent_indexer=self.indexer)
            except Exception as e:
                wx.MessageBox(f"Erreur lors du chargement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_toggle_view(self, event):
        """Switch between list view and timeline view."""
        self._timeline_mode = not self._timeline_mode
        if self._timeline_mode:
            self.list_ctrl.Hide()
            self.timeline_panel.Show()
            self.view_toggle_btn.SetLabel("Vue liste")
        else:
            self.timeline_panel.Hide()
            self.list_ctrl.Show()
            self.view_toggle_btn.SetLabel("Chronologie")
        self.left_container.Layout()
        self._refresh_list()

    def _show_empty_state(self, empty):
        """Message centré quand le filtre / la recherche ne renvoie aucun projet."""
        self.empty_label.Show(bool(empty))
        self.left_container.Layout()

    def _on_timeline_item_selected(self, p_data):
        """Show project details when a timeline card is clicked."""
        self.details_panel.Show()
        self.comparison_panel.Hide()
        self.right_container.Layout()
        if p_data.get('filepath'):
            self.details_panel.load_project(p_data['filepath'])

    def _on_timeline_item_activated(self, p_data):
        """Open project editor on double-click of a timeline card."""
        filepath = p_data.get('filepath')
        if filepath:
            try:
                QuoteEditor_app.open_quote_from_file(filepath, parent_frame=self, parent_indexer=self.indexer)
            except Exception as e:
                wx.MessageBox(f"Impossible d'ouvrir le projet: {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_reset(self, event):
        """Clear all filters and show all projects"""
        self.search_global.SetValue("")
        self.sort_col = "last_modified"
        self.sort_ascending = False
        self._refresh_list()

    def _on_search(self, event):
        """Trigger global search"""
        term = self.search_global.GetValue()
        self._refresh_list(term)

    def _on_col_click(self, event):
        col_idx = event.GetColumn()
        col_name = self.list_ctrl.GetColumn(col_idx).GetText()
        if self.sort_col == col_name:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_col = col_name
            self.sort_ascending = True
            
        self._on_search(None)

    def _refresh_list(self, term=None):
        if term is None: term = self.search_global.GetValue()

        sort_order = "ASC" if self.sort_ascending else "DESC"
        results = self.db.search_projects(
            global_search=term,
            sort_by=self.sort_col,
            sort_order=sort_order
        )

        # Build project_map for all modes (needed by context menu, etc.)
        self.project_map = {}

        if self._timeline_mode:
            self._update_kpis(results)
            if self._mode_filter == "serie":
                results = [p for p in results if p.get('has_serie')]
            elif self._mode_filter == "proto":
                results = [p for p in results if p.get('is_prototype')]
            self._show_empty_state(False)
            self.timeline_panel.load_events(results)
            self.SetStatusText(f"{len(results)} projets affichés")
            self._update_checked_ui()
            return

        self.list_ctrl.DeleteAllItems()

        self._update_kpis(results)
        if self._mode_filter == "serie":
            results = [p for p in results if p.get('has_serie')]
        elif self._mode_filter == "proto":
            results = [p for p in results if p.get('is_prototype')]
        self._show_empty_state(not results)

        for i, p in enumerate(results):
            has_serie    = bool(p.get('has_serie', 0))
            is_prototype = bool(p.get('is_prototype', 0))

            if is_prototype and has_serie:
                mode_label = "Proto + Série"
            elif is_prototype:
                mode_label = "Prototype"
            elif has_serie:
                mode_label = "Série"
            else:
                mode_label = "Lot"

            revision = p.get('last_offer_revision')
            status_label = f"Indice {revision}" if revision else "Brouillon"

            idx = self.list_ctrl.InsertItem(i, str(p.get('reference') or ""))
            self.list_ctrl.SetItem(idx, 1, str(p.get('client') or ""))
            self.list_ctrl.SetItem(idx, 2, status_label)
            self.list_ctrl.SetItem(idx, 3, mode_label)
            self.list_ctrl.SetItem(idx, 4, _fmt_date(p.get('last_offer_at')) if p.get('last_offer_at') else "—")

            if is_prototype:
                self.list_ctrl.SetItemBackgroundColour(idx, UI_ROW_PROTO)
            elif has_serie:
                self.list_ctrl.SetItemBackgroundColour(idx, UI_ROW_SERIE)
            elif i % 2:
                self.list_ctrl.SetItemBackgroundColour(idx, UI_ROW_ALT)

            self.project_map[idx] = p

        n = len(results)
        self.SetStatusText(f"{n} projet{'s' if n > 1 else ''} affiché{'s' if n > 1 else ''}")
        # New filtered set -> checkboxes are cleared; refresh master checkbox + button.
        self._update_checked_ui()

    # ------------------------------------------------------------------ #
    # Multi-selection via checkboxes                                        #
    # ------------------------------------------------------------------ #
    def _get_checked_indices(self):
        """Indices of rows whose checkbox is ticked (empty if unsupported)."""
        indices = []
        try:
            for idx in range(self.list_ctrl.GetItemCount()):
                if self.list_ctrl.IsItemChecked(idx):
                    indices.append(idx)
        except AttributeError:
            pass
        return indices

    def _get_checked_projects(self):
        """p_data of checked rows; falls back to highlighted selection if none."""
        indices = self._get_checked_indices()
        if not indices:
            idx = self.list_ctrl.GetFirstSelected()
            while idx != -1:
                indices.append(idx)
                idx = self.list_ctrl.GetNextSelected(idx)
        return [self.project_map[i] for i in indices if i in self.project_map]

    def _update_checked_ui(self):
        """Sync master checkbox tri-state, export button label/state."""
        if self._timeline_mode:
            self.select_all_cb.SetValue(False)
            self.select_all_cb.Disable()
            self.synth_export_btn.Disable()
            self.synth_export_btn.SetLabel("Exporter synthèse Excel")
            return

        self.select_all_cb.Enable()
        total = self.list_ctrl.GetItemCount()
        checked = len(self._get_checked_indices())

        # Plain 2-state checkbox: ticked as soon as at least one row is checked.
        self.select_all_cb.SetValue(total > 0 and checked > 0)

        if checked > 0:
            self.synth_export_btn.Enable()
            self.synth_export_btn.SetLabel(f"Exporter synthèse Excel ({checked})")
        else:
            self.synth_export_btn.Disable()
            self.synth_export_btn.SetLabel("Exporter synthèse Excel")

    def _on_item_checked(self, event):
        self._update_checked_ui()
        event.Skip()

    def _on_master_check(self, event):
        """Check/uncheck every displayed (filtered) row."""
        check = self.select_all_cb.GetValue()
        try:
            for idx in range(self.list_ctrl.GetItemCount()):
                self.list_ctrl.CheckItem(idx, check)
        except AttributeError:
            pass
        self._update_checked_ui()

    def _on_item_selected(self, event):
        """Update display based on selection count (Details vs Comparison)"""
        count = self.list_ctrl.GetSelectedItemCount()
        
        # Hide/Show panels
        if count <= 1:
            self.details_panel.Show()
            self.comparison_panel.Hide()
        else:
            self.details_panel.Hide()
            self.comparison_panel.Show()
        
        self.right_container.Layout()
        
        # Update Content
        if count == 1:
            idx = event.GetIndex()
            if idx in self.project_map:
                p_data = self.project_map[idx]
                self.details_panel.load_project(p_data['filepath'])
        elif 2 <= count <= 4:
            # Multi-selection -> Automatic comparison
            selected_indices = []
            idx = self.list_ctrl.GetFirstSelected()
            while idx != -1:
                selected_indices.append(idx)
                idx = self.list_ctrl.GetNextSelected(idx)
            
            filepaths = [self.project_map[i]['filepath'] for i in selected_indices]
            self.comparison_panel.load_projects(filepaths)
        elif count > 4:
            self.details_panel.Show()
            self.comparison_panel.Hide()
            self.details_panel.reset_view("Selection trop importante (max 4 pour comparaison).")
            self.right_container.Layout()

    def _on_item_activated(self, event):
        """Handle double-click to open in editor (modal)"""
        idx = event.GetIndex()
        if idx in self.project_map:
            p_data = self.project_map[idx]
            filepath = p_data['filepath']
            try:
                QuoteEditor_app.open_quote_from_file(filepath, parent_frame=self, parent_indexer=self.indexer)
            except Exception as e:
                wx.MessageBox(f"Impossible d'ouvrir le projet: {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_index_dir(self, event):
        with wx.DirDialog(self, "Choisir le dossier racine des projets", 
                          style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dirDialog:
            if dirDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            path = dirDialog.GetPath()
            self.SetStatusText(f"Indexation de {path}...")
            
            btn = event.GetEventObject() if event else None
            if btn: btn.Disable()
            
            def progress(msg):
                wx.CallAfter(self.SetStatusText, msg)
                
            def complete(count):
                wx.CallAfter(self._on_index_complete, count, btn)
                
            self.indexer.index_directory(path, progress_callback=progress, completion_callback=complete)


    def _on_duplicate(self, event):
        """Handle duplication of the selected project file"""
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1:
            wx.MessageBox("Veuillez sélectionner un projet à dupliquer.", "Information", wx.OK | wx.ICON_INFORMATION)
            return
            
        # Ensure only one is selected for duplication
        if self.list_ctrl.GetSelectedItemCount() > 1:
            wx.MessageBox("Veuillez ne sélectionner qu'un seul projet pour la duplication.", "Information", wx.OK | wx.ICON_INFORMATION)
            return

        p_data = self.project_map[idx]
        src_path = p_data['filepath']
        
        base, ext = os.path.splitext(src_path)
        dst_path = base + "_copie" + ext
        
        # Ensure we don't overwrite if it already exists (add increment if needed, but for now simple suffix)
        try:
            # Load project, clone to reset milestones, and save
            project = PersistenceService.load_project(src_path)
            cloned_project = project.clone()
            PersistenceService.save_project(cloned_project, dst_path)
            
            # Re-index the new file
            self.indexer.index_file(dst_path)
            self._refresh_list()
            wx.MessageBox(
                f"Projet dupliqué vers :\n{os.path.basename(dst_path)}\n"
                f"(fichier indépendant)",
                "Succès",
                wx.OK | wx.ICON_INFORMATION
            )
        except Exception as e:
            wx.MessageBox(f"Erreur lors de la duplication : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_delete_project(self, event):
        """Handle deletion of the selected project(s)"""
        # Get all selected items
        selected_indices = []
        idx = self.list_ctrl.GetFirstSelected()
        while idx != -1:
            selected_indices.append(idx)
            idx = self.list_ctrl.GetNextSelected(idx)
        
        if not selected_indices:
            wx.MessageBox("Veuillez sélectionner au moins un projet à supprimer.", "Information", wx.OK | wx.ICON_INFORMATION)
            return
        
        # Build list of projects to delete
        projects_to_delete = []
        for idx in selected_indices:
            if idx in self.project_map:
                p_data = self.project_map[idx]
                projects_to_delete.append(p_data)
        
        if not projects_to_delete:
            return
        
        # Single or multiple deletion?
        if len(projects_to_delete) == 1:
            self._delete_single_project(projects_to_delete[0])
        else:
            self._delete_multiple_projects(projects_to_delete)

    def _delete_single_project(self, p_data):
        """Delete a single project with confirmations"""
        project_id = p_data['id']
        filepath = p_data['filepath']
        
        # 1. Main Confirmation
        res = wx.MessageBox(f"Voulez-vous supprimer le projet '{p_data['name']}' de la base de données ?", 
                           "Confirmation de suppression", wx.YES_NO | wx.ICON_WARNING | wx.NO_DEFAULT)
        
        if res != wx.YES:
            return
            
        # 2. File Deletion Confirmation
        delete_file = False
        if os.path.exists(filepath):
            res_file = wx.MessageBox(f"Voulez-vous également supprimer définitivement le fichier Physique du disque ?\n\n{filepath}", 
                                    "Suppression du fichier", wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT)
            delete_file = (res_file == wx.YES)
            
        try:
            # Delete from DB
            self.db.delete_project(project_id)
            
            # Delete from Disk if requested
            if delete_file:
                try:
                    os.remove(filepath)
                except Exception as fe:
                    wx.MessageBox(f"Le projet a été retiré de la base, mais le fichier n'a pas pu être supprimé :\n{fe}", 
                                 "Erreur fichier", wx.OK | wx.ICON_ERROR)
            
            self._refresh_list()
            self.details_panel.reset_view("Aucun projet sélectionné")
            
            wx.MessageBox("Projet supprimé avec succès.", "Succès", wx.OK | wx.ICON_INFORMATION)
            
        except Exception as e:
            wx.MessageBox(f"Erreur lors de la suppression : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _delete_multiple_projects(self, projects_to_delete):
        """Delete multiple projects with bulk confirmation"""
        count = len(projects_to_delete)
        project_list = "\n".join([f"• {p['name']}" for p in projects_to_delete[:10]])
        if count > 10:
            project_list += f"\n... et {count - 10} autres"
        
        # Main Confirmation
        res = wx.MessageBox(
            f"Voulez-vous supprimer ces {count} projets de la base de données ?\n\n{project_list}",
            "Confirmation de suppression en masse",
            wx.YES_NO | wx.ICON_WARNING | wx.NO_DEFAULT
        )
        
        if res != wx.YES:
            return
        
        # File Deletion Confirmation
        res_file = wx.MessageBox(
            f"Voulez-vous également supprimer définitivement les {count} fichiers physiques du disque ?",
            "Suppression des fichiers",
            wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT
        )
        delete_files = (res_file == wx.YES)
        
        # Progress dialog
        progress = wx.ProgressDialog(
            "Suppression en masse",
            "Suppression en cours...",
            maximum=count,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_CAN_ABORT
        )
        
        deleted_count = 0
        file_errors = []
        db_errors = []
        
        try:
            for i, p_data in enumerate(projects_to_delete):
                project_id = p_data['id']
                filepath = p_data['filepath']
                
                wx.CallAfter(progress.Update, i, f"Suppression {i+1}/{count}: {p_data['name']}")
                
                try:
                    # Delete from DB
                    self.db.delete_project(project_id)
                    
                    # Delete from Disk if requested
                    if delete_files and os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception as fe:
                            file_errors.append(f"{p_data['name']}: {str(fe)}")
                    
                    deleted_count += 1
                    
                except Exception as e:
                    db_errors.append(f"{p_data['name']}: {str(e)}")
        
        finally:
            progress.Destroy()
        
        # Refresh and show summary
        self._refresh_list()
        self.details_panel.reset_view(f"{deleted_count} projets supprimés.")
        
        msg = f"Suppression terminée!\n\n{deleted_count}/{count} projets supprimés."
        if file_errors:
            msg += f"\n\n{len(file_errors)} erreurs fichier :\n" + "\n".join(file_errors[:5])
        if db_errors:
            msg += f"\n\n{len(db_errors)} erreurs BD :\n" + "\n".join(db_errors[:5])
        
        wx.MessageBox(msg, "Suppression en masse", wx.OK | wx.ICON_INFORMATION)


    def _on_index_complete(self, count, btn=None):
        self.SetStatusText(f"Indexation terminée. {count} projets indexés.")
        if btn:
            btn.Enable()
        self._refresh_list()
        wx.MessageBox(f"Indexation terminée.\n{count} projets trouvés.", "Succès", wx.OK | wx.ICON_INFORMATION)

    def _build_ai_project_record(self, project, db_row, anon_client):
        """Create one anonymized project payload with usage + cost structure."""
        def enum_val(v):
            return getattr(v, "value", v)

        def tiers_payload(pricing):
            tiers = []
            if not pricing:
                return tiers
            for t in (pricing.tiers or []):
                tiers.append({
                    "min_quantity": t.min_quantity,
                    "unit_price": t.unit_price,
                    "description": t.description,
                })
            return tiers

        operations_payload = []
        cost_type_counts = {}
        total_costs = 0

        for op_idx, op in enumerate(project.operations, 1):
            costs_payload = []
            for cost_key, cost in op.costs.items():
                total_costs += 1
                ctype = enum_val(cost.cost_type)
                cost_type_counts[ctype] = cost_type_counts.get(ctype, 0) + 1

                pricing = cost.pricing
                costs_payload.append({
                    "key": cost_key,
                    "name": cost.name,
                    "cost_type": ctype,
                    "is_active": bool(getattr(cost, "is_active", True)),
                    "method_comment": cost.comment or "",
                    "client_comment": getattr(cost, "client_comment", "") or "",
                    "supplier_quote_ref": cost.supplier_quote_ref or "",
                    "conversion_type": enum_val(cost.conversion_type),
                    "conversion_factor": cost.conversion_factor,
                    "margin_rate": cost.margin_rate,
                    "quantity_per_piece": cost.quantity_per_piece,
                    "quantity_per_piece_is_inverse": bool(cost.quantity_per_piece_is_inverse),
                    "internal_operation": {
                        "fixed_time_h": cost.fixed_time,
                        "per_piece_time_h": cost.per_piece_time,
                        "hourly_rate": cost.hourly_rate,
                    },
                    "pricing": {
                        "pricing_type": enum_val(pricing.pricing_type) if pricing else None,
                        "unit": pricing.unit if pricing else None,
                        "fixed_price": pricing.fixed_price if pricing else 0.0,
                        "unit_price": pricing.unit_price if pricing else 0.0,
                        "tiers": tiers_payload(pricing),
                    },
                    "documents_count": len(getattr(cost, "documents", []) or []),
                })

            operations_payload.append({
                "index": op_idx,
                "code": op.code,
                "label": op.label,
                "typology": op.typology,
                "comment": op.comment or "",
                "costs_count": len(op.costs),
                "costs": costs_payload,
            })

        project_uuid = db_row.get("mwq_uuid") or getattr(project, "mwq_uuid", None) or ""
        return {
            "project_uuid": project_uuid,
            "reference": project.reference,
            "name": project.name,
            "client_anonymized": anon_client,
            "project_date": project.project_date,
            "sale_quantities": list(project.sale_quantities or []),
            "volume_margin_rates": dict(project.volume_margin_rates or {}),
            "last_modified_db": db_row.get("last_modified"),
            "usage_summary": {
                "operations_count": len(project.operations),
                "costs_count": total_costs,
                "cost_type_counts": cost_type_counts,
            },
            "operations": operations_payload,
        }

    def _do_index(self, folder: str, migrate: bool = False):
        """Helper to run indexing on a folder."""
        self.SetStatusText(f"Indexation de {folder}...")

        def progress(msg):
            wx.CallAfter(self.SetStatusText, msg)

        def complete(count):
            wx.CallAfter(self._on_index_complete, count, None)

        self.indexer.index_directory(folder, progress_callback=progress,
                                    completion_callback=complete, migrate_to_zip=migrate)

    def _do_auto_migrate(self, old_folder: str, new_folder: str):
        """Perform automatic migration when root folder changes."""
        progress_dlg = wx.ProgressDialog(
            "Migration en cours",
            "Préparation de la migration...",
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        
        try:
            def on_progress(msg):
                wx.CallAfter(progress_dlg.Pulse, msg)
            
            def on_complete(stats):
                wx.CallAfter(progress_dlg.Destroy)
                
                msg = (f"Migration terminée !\n\n"
                       f"UUIDs assignés : {stats.get('uuid_assigned', 0)}\n"
                       f"Fichiers relocalisés : {stats.get('files_relocated', 0)}")
                
                if stats.get('errors'):
                    msg += f"\n\nErreurs : {len(stats['errors'])}"
                
                wx.MessageBox(msg, "Migration", wx.OK | wx.ICON_INFORMATION)
                self._refresh_list()
            
            self.migration_service.migrate_on_root_folder_change(
                old_folder, new_folder, on_progress, on_complete
            )
        except Exception as e:
            progress_dlg.Destroy()
            wx.MessageBox(f"Erreur lors de la migration : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_list_right_click(self, event):
        """Show context menu on right-click in list"""
        # Get mouse position relative to the ListCtrl
        mouse_pos = wx.GetMousePosition()
        client_pos = self.list_ctrl.ScreenToClient(mouse_pos)
        
        # Find the item at that position
        idx, flags = self.list_ctrl.HitTest(client_pos)
        
        if idx == -1:
            # No item clicked, ignore
            event.Skip()
            return
        
        # Select the item if not already selected
        if not self.list_ctrl.IsSelected(idx):
            self.list_ctrl.Select(idx, True)
            self.list_ctrl.EnsureVisible(idx)
        
        # Get count of selected items
        selection_count = self.list_ctrl.GetSelectedItemCount()
        
        # Create context menu
        menu = wx.Menu()

        # Export as XLSX (works with single or multiple selections)
        export_item = menu.Append(wx.ID_ANY, f"💾 Exporter vers XLSX" + (f" ({selection_count} fichiers)" if selection_count > 1 else ""),
                                  "Export vers fichier Excel")
        self.Bind(wx.EVT_MENU, self._on_quick_export_xlsx, export_item)

        # Synthesis export (single consolidated Excel) — uses checked rows if any.
        checked_count = len(self._get_checked_indices())
        synth_label = "📊 Exporter synthèse Excel"
        if checked_count > 0:
            synth_label += f" ({checked_count} cochées)"
        synth_item = menu.Append(wx.ID_ANY, synth_label,
                                 "Générer un Excel unique de synthèse (preview + gamme + prix)")
        self.Bind(wx.EVT_MENU, self._on_export_synthesis, synth_item)

        # Export Fabrication/Qualité (works with single selection only)
        if selection_count == 1:
            fab_export_item = menu.Append(wx.ID_ANY, "🏭 Exporter Fabrication/Qualité",
                                          "Export Excel avec trame de fabrication et commentaires")
            self.Bind(wx.EVT_MENU, self._on_export_fabrication_quality, fab_export_item)

        # Edit (only for single selection)
        if selection_count == 1:
            edit_item = menu.Append(wx.ID_ANY, "✎ Éditer\tCtrl+O", "Ouvrir dans l'éditeur")
            self.Bind(wx.EVT_MENU, self._on_context_edit, edit_item)
            
            menu.AppendSeparator()
            
            # Duplicate (only for single selection)
            dup_item = menu.Append(wx.ID_ANY, "🗂️ Dupliquer", "Créer une copie du projet")
            self.Bind(wx.EVT_MENU, self._on_duplicate, dup_item)
        else:
            menu.AppendSeparator()
        
        # Delete (works with single or multiple selections)
        del_item = menu.Append(wx.ID_ANY, f"🗑️ Supprimer" + (f" ({selection_count} fichiers)" if selection_count > 1 else ""), 
                               "Supprimer le(s) projet(s)")
        self.Bind(wx.EVT_MENU, self._on_delete_project, del_item)
        
        # Show menu at client position (PopupMenu expects client coordinates)
        self.PopupMenu(menu, client_pos)
        menu.Destroy()
        
        event.Skip()

    def _on_quick_export_xlsx(self, event):
        """Quick export to XLSX with automatic numbering and template (supports multiple selection)"""
        # Get all selected items
        selected_indices = []
        idx = self.list_ctrl.GetFirstSelected()
        while idx != -1:
            selected_indices.append(idx)
            idx = self.list_ctrl.GetNextSelected(idx)
        
        if not selected_indices:
            wx.MessageBox("Veuillez sélectionner au moins un projet à exporter.", "Information", wx.OK | wx.ICON_INFORMATION)
            return
        
        # Check for template
        template_path = str(get_template_path())
        if not os.path.exists(template_path):
            wx.MessageBox(
                f"Le template est introuvable à l'adresse :\n{template_path}\n\n"
                f"Veuillez vérifier que le fichier TEMPLATE.xlsx est présent dans le dossier 'assets' de l'application.",
                "Template manquant",
                wx.OK | wx.ICON_ERROR
            )
            return
        
        # For multiple selections, propose directory instead of individual files
        if len(selected_indices) > 1:
            with wx.DirDialog(
                self,
                "Sélectionner le dossier de destination pour les exports",
                defaultPath=os.path.expanduser("~\\Desktop"),
                style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST
            ) as dirDialog:
                
                if dirDialog.ShowModal() != wx.ID_OK:
                    return
                
                output_dir = dirDialog.GetPath()
                
                # Show progress dialog
                progress = wx.ProgressDialog(
                    "Export Excel - Fichiers multiples",
                    "Initialisation...",
                    maximum=len(selected_indices),
                    style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_CAN_ABORT
                )
                
                success_count = 0
                error_list = []
                
                try:
                    for i, item_idx in enumerate(selected_indices):
                        p_data = self.project_map.get(item_idx)
                        if not p_data:
                            continue
                        
                        try:
                            project = PersistenceService.load_project(p_data['filepath'])
                            reference = self.export_service.get_devis_reference(project=project)
                            default_filename = self.export_service.get_default_filename(project, devis_ref=reference)
                            output_path = os.path.join(output_dir, default_filename)
                            
                            # Update progress
                            wx.CallAfter(progress.Update, i, f"Export {i+1}/{len(selected_indices)}: {p_data['reference']}")
                            
                            # Generate Excel file
                            self.export_service.export_excel(
                                project,
                                template_path,
                                output_path,
                                project_save_path=p_data['filepath'],
                                devis_ref=reference
                            )

                            success_count += 1
                            logger.info(f"Export successful: {output_path}")
                            
                        except Exception as e:
                            error_list.append(f"{p_data['reference']}: {str(e)}")
                            logger.error(f"Export failed for {p_data['reference']}: {e}")
                
                finally:
                    progress.Destroy()
                
                # Pas de popup de validation : seules les erreurs sont signalées.
                if error_list:
                    msg = (f"{len(error_list)} export(s) en erreur sur {len(selected_indices)} :\n"
                           + "\n".join(error_list[:5]))
                    if len(error_list) > 5:
                        msg += f"\n... et {len(error_list) - 5} autres"
                    wx.MessageBox(msg, "Export Excel", wx.OK | wx.ICON_WARNING)
                self._refresh_list()
                return
        
        # Single file export
        p_data = self.project_map.get(selected_indices[0])
        if not p_data:
            return
        
        try:
            # Load project
            project = PersistenceService.load_project(p_data['filepath'])
            
            # Generate reference with auto-incrementing counter
            reference = self.export_service.get_devis_reference(project=project)
            
            # Propose save location with suggested name using export service
            default_filename = self.export_service.get_default_filename(project, devis_ref=reference)
            
            with wx.FileDialog(
                self,
                "Enregistrer le devis Excel",
                defaultDir=os.path.expanduser("~\\Desktop"),
                defaultFile=default_filename,
                wildcard="Fichiers Excel (*.xlsx)|*.xlsx",
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
            ) as fileDialog:
                
                if fileDialog.ShowModal() != wx.ID_OK:
                    return
                
                output_path = fileDialog.GetPath()
                
                # Show progress
                progress = wx.ProgressDialog(
                    "Export Excel",
                    "Génération du fichier à partir du template...",
                    style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
                )
                
                try:
                    # Generate Excel file from template
                    self.export_service.export_excel(
                        project,
                        template_path,
                        output_path,
                        project_save_path=p_data['filepath'],
                        devis_ref=reference
                    )

                    progress.Destroy()

                    # Try to open the file automatically
                    try:
                        os.startfile(output_path)
                    except Exception as e:
                        logger.warning(f"Impossible d'ouvrir le fichier automatiquement: {e}")

                    # Refresh list and reload details panel to show updated history
                    self._refresh_list()
                    self.details_panel.load_project(p_data['filepath'])
                    
                except PermissionError as perm_error:
                    progress.Destroy()
                    wx.MessageBox(
                        f"Impossible d'enregistrer le fichier.\n\n"
                        f"Vérifiez que :\n"
                        f"- Le fichier n'est pas ouvert dans Excel\n"
                        f"- Vous avez les permissions d'écriture\n\n"
                        f"Détail: {perm_error}",
                        "Erreur d'accès",
                        wx.OK | wx.ICON_ERROR
                    )
                    logger.error(f"Permission error during export: {perm_error}")
                    
                except Exception as export_error:
                    progress.Destroy()
                    logger.error(f"Export error: {export_error}", exc_info=True)
                    wx.MessageBox(
                        f"Erreur lors de l'export Excel :\n{export_error}",
                        "Erreur",
                        wx.OK | wx.ICON_ERROR
                    )
        
        except Exception as e:
            logger.error(f"Quick export error: {e}", exc_info=True)
            wx.MessageBox(
                f"Erreur lors de l'export :\n{str(e)}",
                "Erreur",
                wx.OK | wx.ICON_ERROR
            )

    def _on_export_synthesis(self, event):
        """Export a single consolidated Excel (preview + gamme + prices) for checked offers."""
        projects_data = self._get_checked_projects()
        if not projects_data:
            wx.MessageBox(
                "Cochez au moins un projet (cases à cocher de la liste) pour générer la synthèse.",
                "Aucun projet sélectionné", wx.OK | wx.ICON_INFORMATION
            )
            return

        default_name = f"Synthese_MWProjet_{dt_module.date.today().strftime('%Y%m%d')}.xlsx"
        with wx.FileDialog(
            self, "Enregistrer la synthèse Excel",
            defaultDir=os.path.expanduser("~\\Desktop"),
            defaultFile=default_name,
            wildcard="Fichiers Excel (*.xlsx)|*.xlsx",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as fileDialog:
            if fileDialog.ShowModal() != wx.ID_OK:
                return
            output_path = fileDialog.GetPath()

        progress = wx.ProgressDialog(
            "Export synthèse Excel",
            "Chargement des projets...",
            maximum=len(projects_data) + 1,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        loaded = []
        errors = []
        try:
            for i, p_data in enumerate(projects_data):
                progress.Update(i, f"Chargement {i + 1}/{len(projects_data)}: {p_data.get('reference', '')}")
                try:
                    loaded.append(PersistenceService.load_project(p_data['filepath']))
                except Exception as e:
                    errors.append(f"{p_data.get('reference', p_data.get('filepath'))}: {e}")
                    logger.error(f"Chargement échoué pour la synthèse: {e}")

            if not loaded:
                progress.Destroy()
                wx.MessageBox("Aucun projet n'a pu être chargé.", "Erreur", wx.OK | wx.ICON_ERROR)
                return

            progress.Update(len(projects_data), "Génération du classeur de synthèse...")
            self.export_service.export_multi_synthesis(loaded, output_path)
            progress.Destroy()

            try:
                os.startfile(output_path)
            except Exception as e:
                logger.warning(f"Impossible d'ouvrir le fichier automatiquement: {e}")

            # Pas de popup de validation : seuls les projets ignorés sont signalés.
            if errors:
                msg = f"{len(errors)} projet(s) ignoré(s) :\n" + "\n".join(errors[:5])
                wx.MessageBox(msg, "Export synthèse", wx.OK | wx.ICON_WARNING)

        except Exception as e:
            try:
                progress.Destroy()
            except Exception:
                pass
            logger.error(f"Export synthèse error: {e}", exc_info=True)
            wx.MessageBox(f"Erreur lors de l'export de la synthèse :\n{e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_export_fabrication_quality(self, event):
        """Export Fabrication/Qualité pour le projet sélectionné"""
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1:
            return
        
        p_data = self.project_map.get(idx)
        if not p_data:
            return
        
        try:
            # Load project
            project = PersistenceService.load_project(p_data['filepath'])
            
            # Ask for output file
            default_name = f"{getattr(project, 'reference', 'Projet')}_Fabrication_Qualite.xlsx"
            with wx.FileDialog(
                self, "Exporter Fabrication/Qualité",
                defaultFile=default_name,
                wildcard="Fichiers Excel (*.xlsx)|*.xlsx",
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
            ) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    return
                
                output_path = fileDialog.GetPath()
            
            # Show progress dialog
            progress = wx.ProgressDialog(
                "Export Fabrication/Qualité",
                "Génération du document...",
                maximum=100,
                parent=self,
                style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
            )
            
            try:
                progress.Update(50, "Création du document Excel...")
                
                # Export
                success = self.export_service.export_fabrication_quality(project, output_path)
                
                progress.Update(100)
                
                if success:
                    # Open the file automatically (same logic as XLSX template export)
                    try:
                        os.startfile(output_path)
                    except Exception as e:
                        logger.warning(f"Impossible d'ouvrir le fichier automatiquement: {e}")
                    
                    wx.MessageBox(
                        f"Export Fabrication/Qualité réussi !\n\nFichier : {output_path}",
                        "Export réussi",
                        wx.OK | wx.ICON_INFORMATION
                    )
                
            finally:
                progress.Destroy()
                
        except Exception as e:
            logger.error(f"Fabrication/Quality export error: {e}", exc_info=True)
            wx.MessageBox(
                f"Erreur lors de l'export Fabrication/Qualité :\n{str(e)}",
                "Erreur",
                wx.OK | wx.ICON_ERROR
            )

    def _on_context_edit(self, event):
        """Edit selected project from context menu"""
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1:
            return
        
        p_data = self.project_map.get(idx)
        if not p_data:
            return
        
        try:
            QuoteEditor_app.open_quote_from_file(
                p_data['filepath'],
                parent_frame=self,
                parent_indexer=self.indexer
            )
        except Exception as e:
            wx.MessageBox(
                f"Impossible d'ouvrir le projet: {e}",
                "Erreur",
                wx.OK | wx.ICON_ERROR
            )

    def _on_restore_database(self, backup_dir=None):
        """Restaurer la base de données et les projets depuis un backup ZIP"""
        root_folder = self.config.get_quotes_root_folder()
        
        # Proposer de sélectionner le fichier backup (par défaut dans le dossier des sauvegardes)
        start_dir = backup_dir or self.config.get_backup_folder()
        with wx.FileDialog(
            self,
            "Sélectionner le fichier backup à restaurer",
            defaultDir=start_dir if start_dir and os.path.isdir(start_dir) else "",
            wildcard="Fichiers ZIP (*.zip)|*.zip",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            backup_path = fileDialog.GetPath()
        
        # Confirmation avant restauration
        msg = (
            f"Vous êtes sur le point de restaurer depuis un backup.\n\n"
            f"Fichier: {os.path.basename(backup_path)}\n\n"
            f"⚠️  ATTENTION: Cette opération va remplacer:\n"
            f"   • La base de données actuelle\n"
            f"   • Les fichiers de projets\n\n"
            f"Les données actuelles seront perdues si elles n'ont pas encore été sauvegardées.\n\n"
            f"Êtes-vous sûr de vouloir continuer?"
        )
        
        dlg = wx.MessageDialog(self, msg, "Confirmation Restore", wx.YES_NO | wx.ICON_WARNING)
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        
        # Progress dialog
        progress = wx.ProgressDialog(
            "Restauration en cours",
            "Extraction du backup...",
            maximum=100,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        
        try:
            wx.BeginBusyCursor()
            progress.Update(25, "Extraction de la base de données...")
            
            self.db.restore_database(backup_path, root_folder)
            
            progress.Update(75, "Mise à jour de l'index...")
            
            # Re-index après restauration
            self._refresh_list()
            
            progress.Update(100, "Restauration terminée!")
            wx.EndBusyCursor()
            progress.Destroy()
            
            wx.MessageBox(
                f"✓ Restauration complétée avec succès!\n\n"
                f"La base de données et les projets ont été restaurés.",
                "Restauration terminée",
                wx.OK | wx.ICON_INFORMATION
            )
            logger.info(f"Restauration depuis: {backup_path}")
            
        except Exception as e:
            wx.EndBusyCursor()
            progress.Destroy()
            logger.error(f"Erreur restauration: {e}", exc_info=True)
            wx.MessageBox(
                f"Erreur lors de la restauration:\n{str(e)}",
                "Erreur",
                wx.OK | wx.ICON_ERROR
            )

    def _on_close(self, event):
        """Handle window close event"""
        self.indexer.stop()
        self.Destroy()

    def _select_and_display_quote(self, filepath):
        """
        Find and display a quote in the list and details panel.
        Used to display newly created quotes.
        
        Args:
            filepath: Path to the .mwq file to display
        """
        try:
            # Find the item in project_map that matches this filepath
            target_idx = None
            for idx, p_data in self.project_map.items():
                if p_data.get('filepath') == filepath:
                    target_idx = idx
                    break
            
            if target_idx is not None:
                # Clear previous selection and select the target item
                self.list_ctrl.Select(target_idx, on=True)
                self.list_ctrl.Focus(target_idx)
                
                # Load project in details panel (in normal view, not timeline)
                if self._timeline_mode:
                    self._on_toggle_view(None)  # Switch to normal list view
                
                # Trigger selection event to load details
                p_data = self.project_map[target_idx]
                self.details_panel.load_project(p_data['filepath'])
                
                # Ensure it's visible
                self.list_ctrl.EnsureVisible(target_idx)
        except Exception as e:
            logger.warning(f"Could not display quote {filepath}: {e}")
