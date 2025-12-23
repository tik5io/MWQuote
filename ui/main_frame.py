# ui/main_frame.py
import wx
from domain.project import Project
from ui.panels.project_panel import ProjectPanel
from ui.panels.operation_cost_editor_panel import OperationCostEditorPanel
from ui.panels.sales_pricing_panel import SalesPricingPanel
from infrastructure.persistence import PersistenceService


class MainFrame(wx.Frame):
    """Fenêtre principale de l'application de chiffrage"""

    def __init__(self, project=None):
        super().__init__(None, title="Application de chiffrage", size=(1200, 800))
        
        if project is None:
            project = Project(name="Nouveau projet", reference="", client="")
        
        self.project = project
        self._build_ui()
        self._create_menu_bar()
        self._connect_events()
        
        self.Centre()
        self.Show()

    def _create_menu_bar(self):
        """Crée la barre de menu"""
        menu_bar = wx.MenuBar()
        
        file_menu = wx.Menu()
        new_item = file_menu.Append(wx.ID_NEW, "&Nouveau\tCtrl+N")
        open_item = file_menu.Append(wx.ID_OPEN, "&Ouvrir...\tCtrl+O")
        save_item = file_menu.Append(wx.ID_SAVE, "&Enregistrer...\tCtrl+S")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "&Quitter\tAlt+F4")
        
        menu_bar.Append(file_menu, "&Fichier")
        self.SetMenuBar(menu_bar)
        
        # Bindings
        self.Bind(wx.EVT_MENU, self._on_new, new_item)
        self.Bind(wx.EVT_MENU, self._on_open, open_item)
        self.Bind(wx.EVT_MENU, self._on_save, save_item)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), exit_item)

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

        main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)

        main_panel.SetSizer(main_sizer)

    def _connect_events(self):
        """Connecte les événements entre les panels"""
        self.editor_panel.on_operation_updated = self._on_operation_updated
        self._update_app_with_project(self.project)

    def _update_app_with_project(self, project):
        """Met à jour tous les panels avec un nouveau projet"""
        self.project = project
        self.project_panel.load_project(self.project)
        self.editor_panel.load_project(self.project)
        self.sales_panel.load_project(self.project)

    def _on_operation_updated(self, operation):
        """Appelé quand une opération est modifiée"""
        self.project_panel.load_project(self.project)
        self.sales_panel.load_project(self.project)

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
                self._update_app_with_project(project)
            except Exception as e:
                wx.MessageBox(f"Erreur lors du chargement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_save(self, event):
        """Enregistre le projet dans un fichier"""
        with wx.FileDialog(self, "Enregistrer le projet", wildcard="Fichiers MWQuote (*.mwq)|*.mwq",
                          style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            path = fileDialog.GetPath()
            try:
                PersistenceService.save_project(self.project, path)
                wx.MessageBox("Projet enregistré avec succès !", "Information", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Erreur lors de l'enregistrement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)
