import wx
import os
import sys
from infrastructure.database import Database
from infrastructure.indexer import Indexer
from infrastructure.persistence import PersistenceService
from domain.project import Project
from ui.frames.main_frame import MainFrame
from ui.panels.search_project_details_panel import ProjectDetailsPanel
from ui.panels.comparison_panel import ComparisonPanel


class SearchFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="MWQuote - Analyse et Recherche", size=(1200, 800))
        
        self.db = Database()
        self.indexer = Indexer(self.db)
        
        self._build_ui()
        self._build_menu()
        self._refresh_list()
        
        self.Centre()
        self.Show()
        
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)

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
        
        # Search fields with labels for clarity
        ref_box = wx.BoxSizer(wx.HORIZONTAL)
        ref_box.Add(wx.StaticText(top_bar_container, label="Réf:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.search_ref = wx.TextCtrl(top_bar_container, style=wx.TE_PROCESS_ENTER)
        ref_box.Add(self.search_ref, 1, wx.EXPAND)
        
        client_box = wx.BoxSizer(wx.HORIZONTAL)
        client_box.Add(wx.StaticText(top_bar_container, label="Client:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.search_client = wx.TextCtrl(top_bar_container, style=wx.TE_PROCESS_ENTER)
        client_box.Add(self.search_client, 1, wx.EXPAND)
        
        tag_box = wx.BoxSizer(wx.HORIZONTAL)
        tag_box.Add(wx.StaticText(top_bar_container, label="Tag:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.search_tag = wx.TextCtrl(top_bar_container, style=wx.TE_PROCESS_ENTER)
        tag_box.Add(self.search_tag, 1, wx.EXPAND)
        
        search_btn = wx.Button(top_bar_container, label="Rechercher")
        search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        
        # Reset button
        reset_btn = wx.Button(top_bar_container, label="X", size=(30, -1))
        reset_btn.Bind(wx.EVT_BUTTON, self._on_reset)
        reset_btn.SetToolTip("Effacer les filtres")

        top_bar.Add(ref_box, 1, wx.ALL | wx.EXPAND, 5)
        top_bar.Add(client_box, 1, wx.ALL | wx.EXPAND, 5)
        top_bar.Add(tag_box, 1, wx.ALL | wx.EXPAND, 5)
        top_bar.Add(search_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        top_bar.Add(reset_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        # Duplication & Deletion
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.duplicate_btn = wx.Button(top_bar_container, label="Dupliquer")
        self.duplicate_btn.Bind(wx.EVT_BUTTON, self._on_duplicate)
        btn_box.Add(self.duplicate_btn, 0, wx.RIGHT, 5)
        
        self.delete_btn = wx.Button(top_bar_container, label="Supprimer")
        self.delete_btn.SetForegroundColour(wx.RED)
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete_project)
        btn_box.Add(self.delete_btn, 0)
        
        top_bar.Add(btn_box, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        top_bar.AddStretchSpacer(1)
        
        top_bar_container.SetSizer(top_bar)
        vbox.Add(top_bar_container, 0, wx.EXPAND | wx.ALL, 5)
        
        # --- Splitter (List & Details) ---
        self.splitter = wx.SplitterWindow(main_panel)
        self.splitter.SetSashGravity(0.5) # Balanced split
        
        # Left: Result List
        self.list_ctrl = wx.ListCtrl(self.splitter, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list_ctrl.InsertColumn(0, "Référence", width=120)
        self.list_ctrl.InsertColumn(1, "Client", width=120)
        self.list_ctrl.InsertColumn(2, "Status", width=100)
        self.list_ctrl.InsertColumn(3, "Q. Min", width=60)
        self.list_ctrl.InsertColumn(4, "Q. Max", width=60)
        self.list_ctrl.InsertColumn(5, "Date Proj.", width=90)
        self.list_ctrl.InsertColumn(6, "Jalons", width=180)
        self.list_ctrl.InsertColumn(7, "Tags", width=100)
        self.list_ctrl.InsertColumn(8, "Modifié le", width=110)
        
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_item_selected)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_item_activated)
        
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
        self.search_ref.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self.search_client.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self.search_tag.Bind(wx.EVT_TEXT_ENTER, self._on_search)

    def _build_menu(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        
        m_maintenance = file_menu.Append(wx.ID_ANY, "Maintenance de la base...", "Ouvrir les outils de maintenance")
        file_menu.AppendSeparator()
        m_exit = file_menu.Append(wx.ID_EXIT, "Quitter", "Quitter l'application")
        
        menubar.Append(file_menu, "&Fichier")
        self.SetMenuBar(menubar)
        
        self.Bind(wx.EVT_MENU, self._on_maintenance, m_maintenance)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), m_exit)

    def _on_reset(self, event):
        self.search_ref.SetValue("")
        self.search_client.SetValue("")
        self.search_tag.SetValue("")
        self._refresh_list()

    def _on_search(self, event):
        ref = self.search_ref.GetValue()
        client = self.search_client.GetValue()
        tag = self.search_tag.GetValue()
        self._refresh_list(ref, client, tag)

    def _refresh_list(self, ref=None, client=None, tag=None):
        self.list_ctrl.DeleteAllItems()
        results = self.db.search_projects(reference=ref, client=client, tag=tag)
        
        self.project_map = {} # Map index to project data
        
        for i, p in enumerate(results):
            idx = self.list_ctrl.InsertItem(i, p['reference'])
            self.list_ctrl.SetItem(idx, 1, p['client'] or "")
            self.list_ctrl.SetItem(idx, 2, p.get('status', ""))
            self.list_ctrl.SetItem(idx, 3, str(p.get('min_qty', 0)))
            self.list_ctrl.SetItem(idx, 4, str(p.get('max_qty', 0)))
            self.list_ctrl.SetItem(idx, 5, p.get('project_date', ""))
            
            # Format milestones summary
            ms = []
            if p.get('date_construction'): ms.append(f"🏗️{p['date_construction']}")
            if p.get('date_finalisee'): ms.append(f"🏁{p['date_finalisee']}")
            if p.get('date_transmise'): ms.append(f"📧{p['date_transmise']}")
            self.list_ctrl.SetItem(idx, 6, " | ".join(ms))

            self.list_ctrl.SetItem(idx, 7, ", ".join(p['tags']))
            # Format timestamp roughly
            ts = p['last_modified']
            self.list_ctrl.SetItem(idx, 8, str(ts)[:16]) # Simplified timestamp
            
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
            self.details_panel.content_txt.SetValue("Selection trop importante (max 4 pour comparaison).")
            self.right_container.Layout()

        # Update Buttons
        self.duplicate_btn.Enable(count == 1)
        self.delete_btn.Enable(count == 1)

    def _on_item_activated(self, event):
        """Handle double-click to open in editor"""
        idx = event.GetIndex()
        if idx in self.project_map:
            p_data = self.project_map[idx]
            filepath = p_data['filepath']
            try:
                project = PersistenceService.load_project(filepath)
                # Open a new MainFrame for this project, passing the filepath
                editor_frame = MainFrame(project=project, clear_logs=False, filepath=filepath)
                editor_frame.SetTitle(f"MWQuote - {project.name}")
                editor_frame.Raise()
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
            wx.MessageBox(f"Projet dupliqué vers :\n{os.path.basename(dst_path)}\n(Jalons remis à zéro)", "Succès", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de la duplication : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_delete_project(self, event):
        """Handle deletion of the selected project"""
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1:
            wx.MessageBox("Veuillez sélectionner un projet à supprimer.", "Information", wx.OK | wx.ICON_INFORMATION)
            return
            
        if self.list_ctrl.GetSelectedItemCount() > 1:
            wx.MessageBox("Veuillez ne sélectionner qu'un seul projet pour la suppression.", "Information", wx.OK | wx.ICON_INFORMATION)
            return

        p_data = self.project_map[idx]
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
            self.details_panel.content_txt.SetValue("Projet supprimé.")
            self.details_panel.title_lbl.SetLabel("Aucun projet sélectionné")
            
            wx.MessageBox("Projet supprimé avec succès.", "Succès", wx.OK | wx.ICON_INFORMATION)
            
        except Exception as e:
            wx.MessageBox(f"Erreur lors de la suppression : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_index_complete(self, count, btn=None):
        self.SetStatusText(f"Indexation terminée. {count} projets indexés.")
        if btn: btn.Enable()
        self._refresh_list()
        wx.MessageBox(f"Indexation terminée.\n{count} projets trouvés.", "Succès", wx.OK | wx.ICON_INFORMATION)

    def _on_maintenance(self, event):
        """Show maintenance dialog with debugging and cleaning tools"""
        stats = self.db.get_stats()
        db_path = self.db.get_db_path()
        
        msg = (f"Maintenance & Debug - MWQuote\n\n"
               f"Fichier : {db_path}\n"
               f"Taille : {stats['db_size_kb']:.1f} KB\n\n"
               f"Statistiques :\n"
               f"- Projets indexés : {stats['total_projects']}\n"
               f"- Clients uniques : {stats['total_clients']}\n"
               f"- Tags uniques : {stats['unique_tags']}\n\n"
               "Actions disponibles :")
               
        choices = [
            "Lancer un Scan de dossier (Indexer)",
            "Vérifier l'intégrité de la base",
            "Supprimer liens vers fichiers inexistants",
            "NETTOYAGE COMPLET (RAZ de l'index)"
        ]
        
        dlg = wx.SingleChoiceDialog(self, msg, "Outils de Maintenance", choices)
        
        if dlg.ShowModal() == wx.ID_OK:
            sel = dlg.GetSelection()
            if sel == 0:
                self._on_index_dir(None)
            elif sel == 1:
                ok = self.db.check_integrity()
                if ok:
                    wx.MessageBox("La base de données est saine (Integrity OK).", "Vérification", wx.OK | wx.ICON_INFORMATION)
                else:
                    wx.MessageBox("ERREUR : La base de données est corrompue !", "Alerte", wx.OK | wx.ICON_ERROR)
            elif sel == 2:
                removed = self.db.delete_missing_files()
                self._refresh_list()
                wx.MessageBox(f"{removed} entrées obsolètes supprimées.", "Nettoyage fini", wx.OK | wx.ICON_INFORMATION)
            elif sel == 3:
                if wx.MessageBox("Voulez-vous vraiment TOUT EFFACER ? L'index devra être reconstruit.", 
                                 "Confirmation RAZ", wx.YES_NO | wx.ICON_WARNING) == wx.YES:
                    self.db.clear_all()
                    self._refresh_list()
                    wx.MessageBox("Base de données réinitialisée (VACUUM OK).", "Succès", wx.OK | wx.ICON_INFORMATION)

    def _on_close(self, event):
        self.indexer.stop()
        self.Destroy()
