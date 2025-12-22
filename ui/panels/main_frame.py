# ui/main_frame.py
import wx
from ui.panels.operations_panel import OperationsPanel
from ui.panels.operation_cost_editor_panel import OperationCostEditorPanel
from ui.panels.project_panel import ProjectPanel
from domain.operation import Operation

class MainFrame(wx.Frame):

    def __init__(self, project=None):
        super().__init__(None, title="Pricing Application", size=wx.Size(1100, 700))
        if project is None:
            from domain.project import Project
            project = Project(name="Default Project", reference="", client="")
        self.project = project
        self._build_ui()
        self.Centre()
        self.Show()


    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Project panel at top
        self.project_panel = ProjectPanel(self)
        self.project_panel.load_project(self.project)
        main_sizer.Add(self.project_panel, 0, wx.EXPAND | wx.ALL, 5)

        # Splitter for operations and editor
        splitter = wx.SplitterWindow(self)
        self.operations_panel = OperationsPanel(splitter)
        self.editor_panel = OperationCostEditorPanel(splitter)
        splitter.SplitVertically(self.operations_panel, self.editor_panel, 350)
        main_sizer.Add(splitter, 1, wx.EXPAND)

        # Connections
        self.operations_panel.on_operation_added = self._on_operation_added
        self.editor_panel.on_operation_updated = self._on_operation_updated

        self.editor_panel.load_project(self.project)

        self.SetSizer(main_sizer)
    
    
    def _on_operation_added(self, operation: Operation):
        self.project.add_operation(operation)
        self.operations_panel.load_operations(self.project.operations)
    
    
    def _on_operation_updated(self, operation: Operation):
        self.operations_panel.load_operations(self.project.operations)