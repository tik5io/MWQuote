# ui/main_frame.py
import wx
from domain.project import Project
from ui.panels.project_panel import ProjectPanel
from ui.panels.operation_cost_editor_panel import OperationCostEditorPanel


class MainFrame(wx.Frame):
    """Fenêtre principale de l'application de chiffrage"""

    def __init__(self, project=None):
        super().__init__(None, title="Application de chiffrage", size=(1200, 750))
        
        if project is None:
            project = Project(name="Nouveau projet", reference="", client="")
        
        self.project = project
        self._build_ui()
        self._connect_events()
        
        self.Centre()
        self.Show()

    def _build_ui(self):
        """Construit l'interface utilisateur"""
        # Panel principal
        main_panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Panel du projet en haut
        self.project_panel = ProjectPanel(main_panel)
        self.project_panel.load_project(self.project)
        main_sizer.Add(self.project_panel, 0, wx.EXPAND | wx.ALL, 5)

        # Panel : éditeur de structure (Tree + Properties)
        self.editor_panel = OperationCostEditorPanel(main_panel)
        main_sizer.Add(self.editor_panel, 1, wx.EXPAND | wx.ALL, 5)

        main_panel.SetSizer(main_sizer)

    def _connect_events(self):
        """Connecte les événements entre les panels"""
        # Quand une opération change dans l'éditeur, mettre à jour le panel projet (totaux)
        self.editor_panel.on_operation_updated = self._on_operation_updated
        
        # Charger le projet dans l'éditeur
        self.editor_panel.load_project(self.project)

    def _on_operation_updated(self, operation):
        """Appelé quand une opération est modifiée"""
        # Mettre à jour le panel projet (totaux)
        self.project_panel.load_project(self.project)
