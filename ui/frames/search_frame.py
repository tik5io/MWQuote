import wx
import os
import sys
import shutil
import io
import json
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
from core.app_icon import get_icon_path, load_icon_from_sheet, get_template_path

logger = get_module_logger("SearchFrame", "search_frame.log")


class SearchFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="MWQuote - Analyse et Recherche", size=(1200, 800))

        self.db = Database()
        self.indexer = Indexer(self.db)
        self.config = ConfigurationService.get_instance()
        self.migration_service = MigrationService(self.db)
        self.export_service = ExportService(db=self.db)
        self.template_manager = TemplateManager(self.db)
        self.analytics_service = AnalyticsService(self.db)
        
        self._build_ui()
        self._build_menu()
        self._set_app_icon()
        # Sorting state (must be before _refresh_list)
        self.sort_col = "last_modified"
        self.sort_ascending = False
        
        self._refresh_list()
        
        self.Centre()
        self.Show()
        
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)

    def _set_app_icon(self):
        try:
            icon_path = get_icon_path()
            if icon_path.exists():
                self.SetIcon(wx.Icon(str(icon_path), wx.BITMAP_TYPE_ICO))
        except Exception:
            pass

    def _on_activate(self, event):
        """Refresh list when window gets focus (return from editor)"""
        if event.GetActive():
            self._refresh_list()
        event.Skip()

    def _build_ui(self):
        main_panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # --- Top Bar (Search & Indexing) ---
        top_bar_container = wx.Panel(main_panel)
        top_bar = wx.BoxSizer(wx.HORIZONTAL)

        # New Quote Button
        new_btn = wx.Button(top_bar_container, label="Nouvelle Quote")
        new_btn.SetBackgroundColour(wx.Colour(70, 130, 180))
        new_btn.SetForegroundColour(wx.WHITE)
        new_btn.Bind(wx.EVT_BUTTON, self._on_new_quote)
        top_bar.Add(new_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        top_bar.Add(wx.StaticLine(top_bar_container, style=wx.LI_VERTICAL), 0, wx.EXPAND | wx.ALL, 5)

        # Unified Search Field
        search_box = wx.BoxSizer(wx.HORIZONTAL)
        search_box.Add(wx.StaticText(top_bar_container, label="Rechercher :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.search_global = wx.TextCtrl(top_bar_container, style=wx.TE_PROCESS_ENTER)
        self.search_global.SetHint("Réf, Client, Tag, Devis...")
        search_box.Add(self.search_global, 1, wx.EXPAND)
        
        # Status Filter
        status_box = wx.BoxSizer(wx.HORIZONTAL)
        status_box.Add(wx.StaticText(top_bar_container, label="Statut :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.status_filter = wx.Choice(top_bar_container, choices=["Tous", "En construction", "Finalisée", "Transmise"])
        self.status_filter.SetSelection(0)
        status_box.Add(self.status_filter, 1, wx.EXPAND)
        
        search_btn = wx.Button(top_bar_container, label="Rechercher")
        search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        
        # Reset button
        reset_btn = wx.Button(top_bar_container, label="X", size=(40, -1))
        reset_btn.Bind(wx.EVT_BUTTON, self._on_reset)
        reset_btn.SetToolTip("Effacer les filtres")

        top_bar.Add(search_box, 3, wx.ALL | wx.EXPAND, 5)
        top_bar.Add(status_box, 1, wx.ALL | wx.EXPAND, 5)
        top_bar.Add(search_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        top_bar.Add(reset_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        top_bar.AddStretchSpacer(1)
        
        top_bar_container.SetSizer(top_bar)
        vbox.Add(top_bar_container, 0, wx.EXPAND | wx.ALL, 5)
        
        # --- Splitter (List & Details) ---
        self.splitter = wx.SplitterWindow(main_panel)
        self.splitter.SetSashGravity(0.5) # Balanced split
        
        # Left: Result List
        self.list_ctrl = wx.ListCtrl(self.splitter, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list_ctrl.InsertColumn(0, "Preview", width=70)
        self.list_ctrl.InsertColumn(1, "Référence", width=120)
        self.list_ctrl.InsertColumn(2, "Client", width=120)
        self.list_ctrl.InsertColumn(3, "Status", width=100)
        self.list_ctrl.InsertColumn(4, "Q. Min", width=60)
        self.list_ctrl.InsertColumn(5, "Q. Max", width=60)
        self.list_ctrl.InsertColumn(6, "Date Proj.", width=90)
        self.list_ctrl.InsertColumn(7, "Jalons", width=180)
        self.list_ctrl.InsertColumn(8, "Devis", width=120)
        self.list_ctrl.InsertColumn(9, "Tags", width=100)
        self.list_ctrl.InsertColumn(10, "Modifié le", width=110)
        
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_item_selected)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_item_activated)
        self.list_ctrl.Bind(wx.EVT_LIST_COL_CLICK, self._on_col_click)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_list_right_click)
        self.list_ctrl.Bind(wx.EVT_RIGHT_UP, self._on_list_right_click)
        
        # Right: Details / Comparison Container
        self.right_container = wx.Panel(self.splitter)
        self.right_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.details_panel = ProjectDetailsPanel(self.right_container)
        self.comparison_panel = ComparisonPanel(self.right_container)
        
        self.right_sizer.Add(self.details_panel, 1, wx.EXPAND)
        self.right_sizer.Add(self.comparison_panel, 1, wx.EXPAND)
        self.comparison_panel.Hide()
        
        self.right_container.SetSizer(self.right_sizer)
        
        self.splitter.SplitVertically(self.list_ctrl, self.right_container, 600)
        self.splitter.SetMinimumPaneSize(100)
        
        vbox.Add(self.splitter, 1, wx.EXPAND)
        
        main_panel.SetSizer(vbox)
        
        # Frame sizer to ensure panel fills frame
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(main_panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)
        
        # Status Bar
        self.CreateStatusBar()
        self.SetStatusText("Prêt")
        
        # Bind search events (Enter key)
        self.search_global.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self.status_filter.Bind(wx.EVT_CHOICE, self._on_search)

    def _build_menu(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        business_menu = wx.Menu()

        m_new = file_menu.Append(wx.ID_NEW, "&Nouvelle Quote\tCtrl+N", "Créer une nouvelle quote")
        m_open = file_menu.Append(wx.ID_OPEN, "&Ouvrir...\tCtrl+O", "Ouvrir un fichier .mwq")
        file_menu.AppendSeparator()
        m_maintenance = file_menu.Append(wx.ID_ANY, "Maintenance de la base...", "Ouvrir les outils de maintenance")
        file_menu.AppendSeparator()
        m_exit = file_menu.Append(wx.ID_EXIT, "Quitter", "Quitter l'application")

        menubar.Append(file_menu, "&Fichier")
        m_business_dashboard = business_menu.Append(wx.ID_ANY, "Dashboard Business", "Ouvrir le dashboard analytics")
        menubar.Append(business_menu, "&Business")
        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self._on_new_quote, m_new)
        self.Bind(wx.EVT_MENU, self._on_open_file, m_open)
        self.Bind(wx.EVT_MENU, self._on_maintenance, m_maintenance)
        self.Bind(wx.EVT_MENU, self._on_open_business_dashboard, m_business_dashboard)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), m_exit)

    def _on_open_business_dashboard(self, event):
        frame = BusinessDashboardFrame(self, self.analytics_service)
        frame.Show()

    def _on_new_quote(self, event):
        """Créer une nouvelle quote et ouvrir l'éditeur (modal)"""
        QuoteEditor_app.open_new_quote(parent_frame=self)

    def _on_open_file(self, event):
        """Ouvrir un fichier .mwq directement"""
        with wx.FileDialog(self, "Ouvrir un projet", wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                          style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            path = fileDialog.GetPath()
            try:
                QuoteEditor_app.open_quote_from_file(path, parent_frame=self, parent_indexer=self.indexer)
            except Exception as e:
                wx.MessageBox(f"Erreur lors du chargement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_reset(self, event):
        """Clear all filters and show all projects"""
        self.search_global.SetValue("")
        self.status_filter.SetSelection(0)
        self.sort_col = "last_modified"
        self.sort_ascending = False
        self._refresh_list()

    def _on_search(self, event):
        """Trigger global search using term and status"""
        term = self.search_global.GetValue()
        status = self.status_filter.GetStringSelection()
        self._refresh_list(term, status)

    def _on_col_click(self, event):
        col_idx = event.GetColumn()
        col_name = self.list_ctrl.GetColumn(col_idx).GetText()
        if col_name == "Preview":
            return
        
        if self.sort_col == col_name:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_col = col_name
            self.sort_ascending = True
            
        self._on_search(None)

    def _refresh_list(self, term=None, status=None):
        if term is None: term = self.search_global.GetValue()
        if status is None: status = self.status_filter.GetStringSelection()
        
        self.list_ctrl.DeleteAllItems()
        sort_order = "ASC" if self.sort_ascending else "DESC"
        results = self.db.search_projects(
            global_search=term,
            status=status,
            sort_by=self.sort_col,
            sort_order=sort_order
        )
        
        self.project_map = {} # Map index to project data
        
        for i, p in enumerate(results):
            has_preview = bool(p.get('preview_filename'))
            idx = self.list_ctrl.InsertItem(i, "Oui" if has_preview else "")
            self.list_ctrl.SetItem(idx, 1, str(p.get('reference') or ""))
            self.list_ctrl.SetItem(idx, 2, str(p.get('client') or ""))
            self.list_ctrl.SetItem(idx, 3, str(p.get('status') or ""))
            self.list_ctrl.SetItem(idx, 4, str(p.get('min_qty', 0)))
            self.list_ctrl.SetItem(idx, 5, str(p.get('max_qty', 0)))
            self.list_ctrl.SetItem(idx, 6, str(p.get('project_date') or ""))
            
            # Format milestones summary
            ms = []
            if p.get('date_construction'): ms.append(f"🏗️{p['date_construction']}")
            if p.get('date_finalisee'): ms.append(f"🏁{p['date_finalisee']}")
            if p.get('date_transmise'): ms.append(f"📧{p['date_transmise']}")
            self.list_ctrl.SetItem(idx, 7, " | ".join(ms))

            self.list_ctrl.SetItem(idx, 8, str(p.get('devis_refs') or ""))
            self.list_ctrl.SetItem(idx, 9, ", ".join(p.get('tags', [])))
            # Format timestamp roughly
            ts = p.get('last_modified', "")
            self.list_ctrl.SetItem(idx, 10, str(ts)[:16]) # Simplified timestamp
            
            self.project_map[idx] = p
            
        self.SetStatusText(f"{len(results)} projets trouvés")

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
                f"(Jalons et exports XLSX remis à zéro)",
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


    def _on_index_and_migrate(self, event):
        """Index directory AND migrate legacy JSON files to ZIP format."""
        with wx.DirDialog(self, "Choisir le dossier à scanner et migrer",
                          style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dirDialog:
            if dirDialog.ShowModal() == wx.ID_CANCEL:
                return

            path = dirDialog.GetPath()

            # Confirmation
            if wx.MessageBox(f"Cette opération va :\n"
                            f"1. Scanner tous les fichiers .mwq dans {path}\n"
                            f"2. Convertir les anciens fichiers JSON vers le format ZIP\n"
                            f"3. Mettre à jour l'index\n\n"
                            f"Continuer ?",
                            "Migration vers ZIP", wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
                return

            self.SetStatusText(f"Migration et indexation de {path}...")

            def progress(msg):
                wx.CallAfter(self.SetStatusText, msg)

            def complete(count):
                wx.CallAfter(self._on_index_complete, count, None)

            self.indexer.index_directory(path, progress_callback=progress,
                                        completion_callback=complete, migrate_to_zip=True)

    def _on_index_complete(self, count, btn=None):
        self.SetStatusText(f"Indexation terminée. {count} projets indexés.")
        if btn:
            btn.Enable()
        self._refresh_list()
        wx.MessageBox(f"Indexation terminée.\n{count} projets trouvés.", "Succès", wx.OK | wx.ICON_INFORMATION)

    def _on_maintenance(self, event):
        """Show maintenance dialog with debugging and cleaning tools"""
        stats = self.db.get_stats()
        db_path = self.db.get_db_path()
        root_folder = self.config.get_quotes_root_folder()

        missing_info = f"\n- Projets manquants : {stats['missing_projects']}" if stats.get('missing_projects', 0) > 0 else ""
        root_info = root_folder if root_folder else "(non défini)"
        msg = (f"Maintenance & Debug - MWQuote\n\n"
               f"Base : {db_path}\n"
               f"Taille : {stats['db_size_kb']:.1f} KB\n"
               f"Dossier racine : {root_info}\n\n"
               f"Statistiques :\n"
               f"- Projets indexés : {stats['total_projects']}{missing_info}\n"
               f"- Clients uniques : {stats['total_clients']}\n"
               f"- Tags uniques : {stats['unique_tags']}\n\n"
               "Actions disponibles :")

        # Build choices dynamically based on whether root folder is set
        choices = []
        if root_folder and os.path.exists(root_folder):
            choices.append(f"Re-scanner le dossier racine")
            choices.append(f"Re-scanner + Migrer vers ZIP")
            choices.append(f"Migrer noms legacy vers UUID")
        choices.extend([
            "Définir/Changer le dossier racine...",
            "Relocaliser les fichiers vers un nouveau dossier...",
            "Réconcilier fichiers déplacés",
            "Vérifier l'intégrité de la base",
            "Générer templates depuis export IA...",
            "Exporter dataset IA anonymisé (clients masqués)",
            "Supprimer liens vers fichiers inexistants",
            "📦 BACKUP DATABASE",
            "📦 RESTORE FROM BACKUP",
            "NETTOYAGE COMPLET (RAZ de l'index)"
        ])

        dlg = wx.SingleChoiceDialog(self, msg, "Outils de Maintenance", choices)

        if dlg.ShowModal() == wx.ID_OK:
            selected = dlg.GetStringSelection()

            if selected == "Re-scanner le dossier racine":
                self._do_index(root_folder, migrate=False)
            elif selected == "Re-scanner + Migrer vers ZIP":
                self._do_index(root_folder, migrate=True)
            elif selected == "Migrer noms legacy vers UUID":
                self._do_migrate_legacy_filenames(root_folder)
            elif selected == "Définir/Changer le dossier racine...":
                self._on_set_root_folder()
            elif selected == "Relocaliser les fichiers vers un nouveau dossier...":
                self._on_relocate_files()
            elif selected == "Réconcilier fichiers déplacés":
                rec_stats = self.indexer.reconcile()
                self._refresh_list()
                wx.MessageBox(f"Réconciliation terminée.\n\n"
                             f"Fichiers vérifiés: {rec_stats['checked']}\n"
                             f"Nouveaux manquants: {rec_stats['missing']}\n"
                             f"Retrouvés: {rec_stats['found']}",
                             "Réconciliation", wx.OK | wx.ICON_INFORMATION)
            elif selected == "Vérifier l'intégrité de la base":
                ok = self.db.check_integrity()
                if ok:
                    wx.MessageBox("La base de données est saine (Integrity OK).", "Vérification", wx.OK | wx.ICON_INFORMATION)
                else:
                    wx.MessageBox("ERREUR : La base de données est corrompue !", "Alerte", wx.OK | wx.ICON_ERROR)
            elif selected == "Générer templates depuis export IA...":
                self._on_generate_templates_from_ai_export()
            elif selected == "Exporter dataset IA anonymisé (clients masqués)":
                self._on_export_ai_dataset()
            elif selected == "Supprimer liens vers fichiers inexistants":
                removed = self.db.delete_missing_files()
                self._refresh_list()
                wx.MessageBox(f"{removed} entrées obsolètes supprimées.", "Nettoyage fini", wx.OK | wx.ICON_INFORMATION)
            elif selected == "📦 BACKUP DATABASE":
                self._on_backup_database()
            elif selected == "📦 RESTORE FROM BACKUP":
                self._on_restore_database()
            elif selected == "NETTOYAGE COMPLET (RAZ de l'index)":
                if wx.MessageBox("Voulez-vous vraiment TOUT EFFACER ? L'index devra être reconstruit.",
                                 "Confirmation RAZ", wx.YES_NO | wx.ICON_WARNING) == wx.YES:
                    self.db.clear_all()
                    self._refresh_list()
                    wx.MessageBox("Base de données réinitialisée (VACUUM OK).", "Succès", wx.OK | wx.ICON_INFORMATION)

    def _on_export_ai_dataset(self):
        """Export anonymized project dataset for AI analysis (business + software usage)."""
        rows = self.db.search_projects(include_missing=False, sort_by="last_modified", sort_order="DESC")
        if not rows:
            wx.MessageBox("Aucun projet indexé à exporter.", "Information", wx.OK | wx.ICON_INFORMATION)
            return

        default_name = f"mwquote_ai_dataset_{date.today().strftime('%Y%m%d')}.json"
        with wx.FileDialog(
            self,
            "Exporter dataset IA anonymisé",
            wildcard="Fichier JSON (*.json)|*.json",
            defaultFile=default_name,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            output_path = dlg.GetPath()

        # Stable pseudonymization labels by client value ordering.
        unique_clients = sorted({(r.get("client") or "").strip() for r in rows})
        client_map = {}
        for idx, client_name in enumerate(unique_clients, 1):
            client_map[client_name] = f"CLIENT_{idx:04d}" if client_name else "CLIENT_0000"

        exported = []
        skipped = []

        for row in rows:
            filepath = row.get("filepath")
            try:
                project = PersistenceService.load_project(filepath)
            except Exception as e:
                skipped.append({"filepath": filepath, "error": str(e)})
                continue

            anon_client = client_map.get((row.get("client") or "").strip(), "CLIENT_0000")
            record = self._build_ai_project_record(project, row, anon_client)
            exported.append(record)

        payload = {
            "schema_version": "1.0",
            "generated_on": date.today().isoformat(),
            "description": (
                "Dataset MWQuote anonymise pour analyses IA: comprehension usage logiciel, "
                "analyse metier des couts, recommandations evolutions produit."
            ),
            "anonymization": {
                "clients_masked": True,
                "project_uuid_preserved": True,
                "note": "Le champ client est pseudonymise; les UUID projet sont conserves."
            },
            "stats": {
                "indexed_projects": len(rows),
                "exported_projects": len(exported),
                "skipped_projects": len(skipped),
                "unique_clients_anonymized": len(unique_clients),
            },
            "projects": exported,
            "skipped": skipped,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        logger.info(f"AI dataset exported: {output_path} | exported={len(exported)} skipped={len(skipped)}")
        msg = (
            f"Export IA terminé.\n\n"
            f"Fichier : {output_path}\n"
            f"Projets exportés : {len(exported)}\n"
            f"Projets ignorés : {len(skipped)}"
        )
        wx.MessageBox(msg, "Export IA anonymisé", wx.OK | wx.ICON_INFORMATION)

    def _on_generate_templates_from_ai_export(self):
        with wx.FileDialog(
            self,
            "Sélectionner un export IA JSON",
            wildcard="Fichier JSON (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            created = self.template_manager.create_initial_templates_from_ai_dataset(path)
            wx.MessageBox(f"Templates générés: {created}", "Templates IA", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Erreur génération templates IA:\n{e}", "Erreur", wx.OK | wx.ICON_ERROR)

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
            "status": project.status,
            "project_date": project.project_date,
            "status_dates": dict(project.status_dates or {}),
            "tags": list(project.tags or []),
            "sale_quantities": list(project.sale_quantities or []),
            "volume_margin_rates": dict(project.volume_margin_rates or {}),
            "export_history_count": len(project.export_history or []),
            "devis_refs_db": db_row.get("devis_refs") or "",
            "last_modified_db": db_row.get("last_modified"),
            "usage_summary": {
                "operations_count": len(project.operations),
                "costs_count": total_costs,
                "cost_type_counts": cost_type_counts,
            },
            "validation_report": getattr(project, "validation_report", {}) or {},
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

    def _on_set_root_folder(self):
        """Set or change the root folder for quotes."""
        current = self.config.get_quotes_root_folder() or ""
        with wx.DirDialog(self, "Définir le dossier racine des quotes",
                          defaultPath=current,
                          style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                new_folder = dlg.GetPath()
                old_folder = self.config.get_quotes_root_folder()
                
                # Update configuration
                self.config.set_quotes_root_folder(new_folder)
                
                # Offer automatic migration if there's an old folder and it's different
                if old_folder and old_folder != new_folder and os.path.exists(old_folder):
                    msg = (f"Ancien dossier : {old_folder}\n"
                           f"Nouveau dossier : {new_folder}\n\n"
                           f"Voulez-vous migrer automatiquement les fichiers existants "
                           f"vers le nouveau dossier ?\n\n"
                           f"Les fichiers seront :\n"
                           f"- Copiés au nouveau dossier\n"
                           f"- Renommés avec UUID si nécessaire\n"
                           f"- L'index sera mis à jour")
                    
                    if wx.MessageBox(msg, "Migration des fichiers", 
                                    wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                        self._do_auto_migrate(old_folder, new_folder)
                    else:
                        wx.MessageBox(f"Dossier racine défini :\n{new_folder}\n\n"
                                    "Vous pouvez migrer les fichiers manuellement "
                                    "via Maintenance > Relocaliser les fichiers",
                                    "Dossier racine", wx.OK | wx.ICON_INFORMATION)
                else:
                    wx.MessageBox(f"Dossier racine défini :\n{new_folder}\n\n"
                                 f"Voulez-vous scanner ce dossier maintenant ?",
                                 "Dossier racine", wx.YES_NO | wx.ICON_QUESTION)
                    if wx.MessageBox(f"Scanner le dossier maintenant ?",
                                    "Scanner", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                        self._do_index(new_folder, migrate=False)

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

    def _on_relocate_files(self):
        """Relocate all indexed files to a new folder."""
        # Get list of current files
        projects = self.db.search_projects(include_missing=False)
        if not projects:
            wx.MessageBox("Aucun projet à relocaliser.", "Information", wx.OK | wx.ICON_INFORMATION)
            return

        with wx.DirDialog(self, "Choisir le nouveau dossier de destination",
                          style=wx.DD_DEFAULT_STYLE) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return

            new_folder = dlg.GetPath()

            # Confirmation
            if wx.MessageBox(f"Cette opération va :\n"
                            f"1. Copier {len(projects)} fichiers .mwq vers :\n   {new_folder}\n"
                            f"2. Mettre à jour les chemins dans la base\n"
                            f"3. Définir ce dossier comme nouveau dossier racine\n\n"
                            f"Les fichiers originaux ne seront PAS supprimés.\n\n"
                            f"Continuer ?",
                            "Relocalisation", wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
                return

            # Progress dialog
            progress_dlg = wx.ProgressDialog("Relocalisation en cours",
                                            "Copie des fichiers...",
                                            maximum=len(projects),
                                            parent=self,
                                            style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL)
            copied = 0
            errors = []

            try:
                for i, p in enumerate(projects):
                    old_path = p['filepath']
                    filename = os.path.basename(old_path)
                    new_path = os.path.join(new_folder, filename)

                    # Handle duplicates
                    if os.path.exists(new_path) and new_path != old_path:
                        base, ext = os.path.splitext(filename)
                        counter = 1
                        while os.path.exists(new_path):
                            new_path = os.path.join(new_folder, f"{base}_{counter}{ext}")
                            counter += 1

                    progress_dlg.Update(i, f"Copie de {filename}...")

                    try:
                        if os.path.exists(old_path):
                            shutil.copy2(old_path, new_path)
                            # Update DB with new path
                            self.db.update_filepath(p['id'], new_path)
                            copied += 1
                    except Exception as e:
                        errors.append(f"{filename}: {e}")

                # Update root folder config
                self.config.set_quotes_root_folder(new_folder)

            finally:
                progress_dlg.Destroy()

            self._refresh_list()

            msg = f"Relocalisation terminée.\n\n{copied} fichiers copiés."
            if errors:
                msg += f"\n\n{len(errors)} erreurs :\n" + "\n".join(errors[:5])
                if len(errors) > 5:
                    msg += f"\n... et {len(errors) - 5} autres"
            wx.MessageBox(msg, "Relocalisation", wx.OK | wx.ICON_INFORMATION)

    def _do_migrate_legacy_filenames(self, root_folder: str):
        """Migrate legacy-named files to UUID-based naming."""
        if wx.MessageBox(
            f"Cette opération va :\n\n"
            f"1. Scanner {root_folder}\n"
            f"2. Identifier les fichiers avec noms legacy\n"
            f"3. Les renommer avec UUID automatique\n"
            f"4. Mettre à jour la base de données\n\n"
            f"Les fichiers originaux seront déplacés.\n\n"
            f"Continuer ?",
            "Migration legacy vers UUID", 
            wx.YES_NO | wx.ICON_QUESTION
        ) != wx.YES:
            return
        
        progress_dlg = wx.ProgressDialog(
            "Migration legacy vers UUID",
            "Scan en cours...",
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        
        try:
            def on_progress(msg):
                wx.CallAfter(progress_dlg.Pulse, msg)
            
            def on_complete(stats):
                wx.CallAfter(progress_dlg.Destroy)
                
                msg = (f"Migration terminée !\n\n"
                       f"Fichiers scannés : {stats.get('scanned', 0)}\n"
                       f"Déjà en UUID : {stats.get('already_uuid', 0)}\n"
                       f"Renommés : {stats.get('migrated', 0)}")
                
                if stats.get('errors'):
                    msg += f"\n\nErreurs : {len(stats['errors'])}"
                
                wx.MessageBox(msg, "Migration", wx.OK | wx.ICON_INFORMATION)
                self._refresh_list()
            
            self.migration_service.auto_migrate_legacy_files(
                root_folder, on_progress, on_complete
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
                            
                            # Update DB
                            if not hasattr(project, 'export_history'):
                                project.export_history = []
                            
                            self.db.update_project_export_history(
                                p_data['id'],
                                '\n'.join([f"{e['date']} - {e.get('devis_ref', 'N/A')}" for e in project.export_history])
                            )
                            
                            success_count += 1
                            logger.info(f"Export successful: {output_path}")
                            
                        except Exception as e:
                            error_list.append(f"{p_data['reference']}: {str(e)}")
                            logger.error(f"Export failed for {p_data['reference']}: {e}")
                
                finally:
                    progress.Destroy()
                
                # Show summary
                msg = f"Export terminé!\n\n{success_count}/{len(selected_indices)} fichiers exportés."
                if error_list:
                    msg += f"\n\n{len(error_list)} erreurs :\n" + "\n".join(error_list[:5])
                    if len(error_list) > 5:
                        msg += f"\n... et {len(error_list) - 5} autres"
                
                wx.MessageBox(msg, "Export Excel", wx.OK | wx.ICON_INFORMATION if success_count > 0 else wx.ICON_WARNING)
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
                    
                    # Update DB with new export history
                    if not hasattr(project, 'export_history'):
                        project.export_history = []
                    
                    self.db.update_project_export_history(
                        p_data['id'],
                        '\n'.join([f"{e['date']} - {e.get('devis_ref', 'N/A')}" for e in project.export_history])
                    )
                    
                    wx.MessageBox(
                        f"Export réussi !\n\n"
                        f"Référence : {reference}\n"
                        f"Fichier : {os.path.basename(output_path)}\n\n"
                        f"Le numéro a été enregistré dans la base de données.",
                        "Succès",
                        wx.OK | wx.ICON_INFORMATION
                    )
                    
                    # Refresh list to show updated export info
                    self._refresh_list()
                    
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

    def _on_backup_database(self):
        """Créer un backup complet: DB + dossier des projets en ZIP"""
        root_folder = self.config.get_quotes_root_folder()
        
        if not root_folder:
            wx.MessageBox(
                "Le dossier racine des projets n'est pas défini.\n"
                "Veuillez d'abord définir le dossier racine dans Maintenance > Définir/Changer le dossier racine.",
                "Dossier racine manquant",
                wx.OK | wx.ICON_WARNING
            )
            return
        
        # Proposer un nom par défaut avec date
        from datetime import datetime
        default_name = f"MWQuote_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        with wx.FileDialog(
            self,
            "Sauvegarder le backup complet",
            defaultFile=default_name,
            wildcard="Fichiers ZIP (*.zip)|*.zip",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            backup_path = fileDialog.GetPath()
        
        # Progress dialog
        progress = wx.ProgressDialog(
            "Création du backup",
            "Compression de la base de données et des projets...",
            maximum=100,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
        )
        
        try:
            wx.BeginBusyCursor()
            progress.Update(25, "Préparation...")
            
            self.db.backup_database_with_projects(backup_path, root_folder)
            
            progress.Update(100, "Backup terminé!")
            wx.EndBusyCursor()
            progress.Destroy()
            
            file_size_mb = os.path.getsize(backup_path) / (1024 * 1024)
            
            msg = (
                f"✓ Backup créé avec succès!\n\n"
                f"Fichier: {os.path.basename(backup_path)}\n"
                f"Taille: {file_size_mb:.2f} MB\n"
                f"Chemin: {backup_path}"
            )
            wx.MessageBox(msg, "Backup terminé", wx.OK | wx.ICON_INFORMATION)
            logger.info(f"Backup créé: {backup_path}")
            
        except Exception as e:
            wx.EndBusyCursor()
            progress.Destroy()
            logger.error(f"Erreur backup: {e}", exc_info=True)
            wx.MessageBox(
                f"Erreur lors du backup:\n{str(e)}",
                "Erreur",
                wx.OK | wx.ICON_ERROR
            )

    def _on_restore_database(self):
        """Restaurer la base de données et les projets depuis un backup ZIP"""
        root_folder = self.config.get_quotes_root_folder()
        
        # Proposer de sélectionner le fichier backup
        with wx.FileDialog(
            self,
            "Sélectionner le fichier backup à restaurer",
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
