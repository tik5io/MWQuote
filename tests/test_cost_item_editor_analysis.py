import unittest

from domain.cost import CostItem, CostType, PricingStructure, PricingType, ConversionType
from ui.components.cost_item_editor import CostItemEditor


class CostItemEditorAnalysisTest(unittest.TestCase):
    def test_analysis_preview_uses_sale_price_with_margin(self):
        pricing = PricingStructure(PricingType.PER_UNIT, fixed_price=10.0, unit_price=20.0, unit="pièce")
        cost = CostItem(
            name="Sous-traitance test",
            cost_type=CostType.SUBCONTRACTING,
            pricing=pricing,
            quantity_per_piece=1.0,
            conversion_type=ConversionType.MULTIPLY,
            conversion_factor=1.0,
            margin_rate=25.0,
        )

        metrics = CostItemEditor.get_analysis_preview_metrics(cost, 10)

        self.assertAlmostEqual(metrics["cost_per_piece"], 21.0)
        self.assertAlmostEqual(metrics["sale_price_per_piece"], 28.0)
        self.assertAlmostEqual(metrics["sale_price_total"], 280.0)

    def test_temps_masque_disables_time_per_piece(self):
        cost = CostItem(
            name="Temps Masqué Test",
            cost_type=CostType.INTERNAL_OPERATION,
            pricing=PricingStructure(PricingType.PER_UNIT),
            fixed_time=2.0,
            per_piece_time=0.5,
            hourly_rate=50.0,
            is_temps_masque=True,
        )
        # Without is_temps_masque:
        # total_time = 2.0 + 0.5 * 10 = 7.0 hours
        # batch_supplier_cost = 7.0 * 50 = 350.0
        # With is_temps_masque=True:
        # total_time = 2.0 + 0.0 * 10 = 2.0 hours
        # batch_supplier_cost = 2.0 * 50 = 100.0
        
        metrics = CostItemEditor.get_analysis_preview_metrics(cost, 10)
        self.assertAlmostEqual(metrics["batch_supplier_cost"], 100.0)

    def test_serie_data_sync_applies_multiplier_divider(self):
        from domain.project import Project
        from domain.operation import Operation
        from domain.serie_data import SerieData

        project = Project(name="Test Project", reference="Ref1", client="Client1")
        op = Operation(code="OP1", label="Op1")
        
        # Cost 1: Multiply (serial) mode
        cost1 = CostItem(
            name="Serial Cost",
            cost_type=CostType.INTERNAL_OPERATION,
            pricing=PricingStructure(PricingType.PER_UNIT),
            per_piece_time=0.1,  # 6 minutes
            conversion_type=ConversionType.MULTIPLY,
            conversion_factor=2.0,
            hourly_rate=30.0,
        )
        
        # Cost 2: Divide (parallel) mode
        cost2 = CostItem(
            name="Parallel Cost",
            cost_type=CostType.INTERNAL_OPERATION,
            pricing=PricingStructure(PricingType.PER_UNIT),
            per_piece_time=0.2,  # 12 minutes
            conversion_type=ConversionType.DIVIDE,
            conversion_factor=4.0,
            hourly_rate=40.0,
        )
        
        # Cost 3: Temps Masqué (ignored in cycle time)
        cost3 = CostItem(
            name="Masked Cost",
            cost_type=CostType.INTERNAL_OPERATION,
            pricing=PricingStructure(PricingType.PER_UNIT),
            per_piece_time=0.5,
            is_temps_masque=True,
            hourly_rate=50.0,
        )

        op.costs = {"c1": cost1, "c2": cost2, "c3": cost3}
        project.operations = [op]

        serie_data = SerieData()
        serie_data.sync_from_project(project)

        # Expected tc_h = (0.1 * 2.0) + (0.2 / 4.0) + 0.0 = 0.2 + 0.05 = 0.25 hours
        # Expected cycle_time_s = 0.25 * 3600 = 900.0 seconds
        self.assertEqual(len(serie_data.machine_posts), 1)
        post = serie_data.machine_posts[0]
        self.assertAlmostEqual(post.cycle_time_s, 900.0)


if __name__ == "__main__":
    unittest.main()
