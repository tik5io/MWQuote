import unittest

from domain.operation import Operation
from ui.panels.operation_cost_editor_panel import OperationCostEditorPanel


class OperationCostEditorPanelToolingTest(unittest.TestCase):
    def test_create_tooling_cost_uses_unique_names(self):
        op = Operation(code="OP1", label="Opération")
        panel = OperationCostEditorPanel.__new__(OperationCostEditorPanel)

        first_cost = panel._create_tooling_cost(op, "Outillage")
        op.costs[first_cost.name] = first_cost

        second_cost = panel._create_tooling_cost(op, "Outillage")

        self.assertEqual(first_cost.name, "Outillage")
        self.assertEqual(second_cost.name, "Outillage 2")


if __name__ == "__main__":
    unittest.main()
