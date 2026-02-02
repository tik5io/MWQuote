# ui/main_frame.py
import wx
import os
from domain.project import Project
from ui.panels.project_panel import ProjectPanel
from ui.panels.operation_cost_editor_panel import OperationCostEditorPanel
from ui.panels.sales_pricing_panel import SalesPricingPanel
from ui.panels.graph_analysis_panel import GraphAnalysisPanel
from infrastructure.persistence import PersistenceService
from infrastructure.logging_service import clear_logs_directory
from infrastructure.export_service import ExportService
from infrastructure.database import Database
from infrastructure.indexer import Indexer






class MainFrame(wx.Frame):
    """Fenêtre principale de l'application de chiffrage"""

    def __init__(self, project=None, clear_logs=False, filepath=None):
        super().__init__(None, title="MWQuote", size=(1200, 800))
        
        if clear_logs:
            clear_logs_directory()

        self.project = project or Project(name="Nouveau Projet", reference="", client="")
        self.current_path = filepath
        
        # Services
        self.db = Database()
        self.indexer = Indexer(self.db)
        
        self._build_ui()
        self._create_menu_bar()
        self._connect_events()
        
        if self.project:
            self._update_app_with_project(self.project)
        
        self.Show()

    def _create_menu_bar(self):
        """Crée la barre de menu"""
        menu_bar = wx.MenuBar()
        
        file_menu = wx.Menu()
        new_item = file_menu.Append(wx.ID_NEW, "&Nouveau\tCtrl+N")
        open_item = file_menu.Append(wx.ID_OPEN, "&Ouvrir...\tCtrl+O")
        file_menu.AppendSeparator()
        save_item = file_menu.Append(wx.ID_SAVE, "&Enregistrer\tCtrl+S")
        save_as_item = file_menu.Append(wx.ID_SAVEAS, "Enregistrer &sous...\tCtrl+Shift+S")
        duplicate_item = file_menu.Append(wx.ID_DUPLICATE, "&Dupliquer")
        file_menu.AppendSeparator()
        export_excel_item = file_menu.Append(wx.ID_ANY, "Exporter Offre (Excel)...")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "&Quitter\tAlt+F4")
        
        menu_bar.Append(file_menu, "&Fichier")
        self.SetMenuBar(menu_bar)
        
        # Bindings
        self.Bind(wx.EVT_MENU, self._on_new, new_item)
        self.Bind(wx.EVT_MENU, self._on_open, open_item)
        self.Bind(wx.EVT_MENU, self._on_save, save_item)
        self.Bind(wx.EVT_MENU, self._on_save_as, save_as_item)
        self.Bind(wx.EVT_MENU, self._on_duplicate, duplicate_item)
        self.Bind(wx.EVT_MENU, self._on_export_excel, export_excel_item)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), exit_item)
        self.Bind(wx.EVT_CLOSE, self._on_close)



    def _build_ui(self):
        """Construit l'interface utilisateur"""
        # Panel principal
        main_panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Panel du projet en haut
        self.project_panel = ProjectPanel(main_panel)
        main_sizer.Add(self.project_panel, 0, wx.EXPAND | wx.ALL, 5)

        # Notebook pour les onglets
        self.notebook = wx.Notebook(main_panel)
        
        # Onglet 1 : Éditeur de structure
        self.editor_panel = OperationCostEditorPanel(self.notebook)
        self.notebook.AddPage(self.editor_panel, "Structure et Coûts")
        
        # Onglet 2 : Tarif de vente
        self.sales_panel = SalesPricingPanel(self.notebook)
        self.notebook.AddPage(self.sales_panel, "Tarif de Vente")
        
        # Onglet 3 : Analyse Graphique
        self.analysis_panel = GraphAnalysisPanel(self.notebook)
        self.notebook.AddPage(self.analysis_panel, "Analyse Graphique")

        main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)

        main_panel.SetSizer(main_sizer)

    def _connect_events(self):
        """Connecte les événements entre les panels"""
        self.editor_panel.on_operation_updated = self._on_operation_updated
        self.project_panel.on_quantities_changed = self._on_quantities_changed
        self.project_panel.on_project_changed = self.editor_panel.update_root_label
        # Note: _update_app_with_project is called in __init__, no need here

    def _update_app_with_project(self, project):
        """Met à jour tous les panels avec un nouveau projet"""
        self.project = project
        self.project_panel.load_project(self.project)
        self.editor_panel.load_project(self.project)
        self.sales_panel.load_project(self.project)
        self.analysis_panel.load_project(self.project)

    def _on_operation_updated(self, operation):
        """Appelé quand une opération est modifiée"""
        # Ne pas recharger le project_panel (header) à chaque touche tapée dans un coût
        # sauf si l'opération elle-même a été ajoutée/supprimée
        if operation is not None:
            self.project_panel.load_project(self.project)
        
        self.sales_panel.refresh_data()
        self.analysis_panel.refresh_data()

    def _on_quantities_changed(self, quantities):
        """Appelé quand les quantités du projet sont modifiées"""
        self.sales_panel.refresh_data()
        self.analysis_panel.refresh_data()
        
        # Refresh all relevant result panels (some are nested in editors)
        if hasattr(self.editor_panel, 'result_panel'):
            self.editor_panel.result_panel._refresh_qty_choice()
            
        if hasattr(self.editor_panel, 'cost_editor') and self.editor_panel.cost_editor.IsShown():
            self.editor_panel.cost_editor.result_panel._refresh_qty_choice()

        if hasattr(self.sales_panel, 'cost_editor') and self.sales_panel.cost_editor.IsShown():
            self.sales_panel.cost_editor.result_panel._refresh_qty_choice()

    def _on_new(self, event):
        """Réinitialise avec un nouveau projet"""
        if wx.MessageBox("Créer un nouveau projet ? Les modifications non enregistrées seront perdues.", 
                        "Nouveau projet", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            new_project = Project(name="Nouveau projet", reference="", client="")
            self._update_app_with_project(new_project)

    def _on_open(self, event):
        """Ouvre un projet depuis un fichier"""
        with wx.FileDialog(self, "Ouvrir un projet", wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                          style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            path = fileDialog.GetPath()
            try:
                project = PersistenceService.load_project(path)
                self.current_path = path
                self._update_app_with_project(project)
            except Exception as e:
                wx.MessageBox(f"Erreur lors du chargement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_save(self, event):
        """Enregistre le projet dans le fichier actuel ou propose 'Enregistrer sous' si inexistant"""
        if self.current_path and os.path.exists(self.current_path):
            try:
                PersistenceService.save_project(self.project, self.current_path)
                # Auto-index in DB
                self.indexer.index_file(self.current_path)
                wx.MessageBox("Projet enregistré avec succès !", "Information", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Erreur lors de l'enregistrement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)
        else:
            self._on_save_as(event)

    def _on_save_as(self, event):
        """Propose un emplacement pour enregistrer le projet sous un nouveau nom"""
        with wx.FileDialog(self, "Enregistrer le projet sous", 
                          defaultFile=os.path.basename(self.current_path) if self.current_path else "",
                          wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                          style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            path = fileDialog.GetPath()
            try:
                PersistenceService.save_project(self.project, path)
                self.current_path = path
                # Auto-index in DB
                self.indexer.index_file(path)
                wx.MessageBox("Projet enregistré avec succès !", "Information", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Erreur lors de l'enregistrement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_duplicate(self, event):
        """Duplique le projet actuel (Save As sans changer le chemin courant d'édition)"""
        if not self.current_path:
            self._on_save_as(event)
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
                wx.MessageBox("Copie créée avec succès (jalons remis à zéro) !", "Information", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Erreur lors de la duplication : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_export_excel(self, event):
        """Exporte le projet vers Excel en utilisant le template"""
        template_path = "TEMPLATE.xlsx"
        if not os.path.exists(template_path):
            wx.MessageBox(f"Template '{template_path}' introuvable.", "Erreur", wx.OK | wx.ICON_ERROR)
            return

        exporter = ExportService()
        default_name = exporter.get_default_filename(self.project)

        with wx.FileDialog(self, "Exporter l'offre Excel", 
                          defaultFile=default_name,
                          wildcard="Fichiers Excel (*.xlsx)|*.xlsx",
                          style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            output_path = fileDialog.GetPath()
            try:
              
                exporter = ExportService()
                exporter.export_excel(
                    self.project,
                    template_path,
                    output_path
                )
                # Automatically open the file after export (Windows specific but safe here)
                try:
                    os.startfile(output_path)
                except Exception as e:
                    logger.warning(f"Impossible d'ouvrir le fichier automatiquement: {e}")

                wx.MessageBox("Offre Excel exportée avec succès !", "Information", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Erreur lors de l'export : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)



    def _on_close(self, event):
        """Appelé à la fermeture de la fenêtre principale"""
        res = wx.MessageBox("Voulez-vous enregistrer les modifications avant de quitter ?", 
                          "Quitter", wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
        
        if res == wx.YES:
            # Trigger save
            self._on_save(None)
            # Final clean and destroy
            clear_logs_directory()
            self.Destroy()
        elif res == wx.NO:
            # Exit without saving
            clear_logs_directory()
            self.Destroy()
        else:
            # Cancel: don't close
            if event.CanVeto():
                event.Veto()