"""Panels subpackage: expose main UI widgets.

Exports:
- `MainFrame`, `OperationsPanel`, `ProjectPanel`, `OperationEditorPanel`
"""

from .main_frame import MainFrame
from .operations_panel import OperationsPanel
from .project_panel import ProjectPanel
from .operation_editor_panel import OperationEditorPanel
from .operation_cost_editor_panel import OperationCostEditorPanel

__all__ = ["MainFrame", "OperationsPanel", "ProjectPanel", "OperationEditorPanel", "OperationCostEditorPanel"]
