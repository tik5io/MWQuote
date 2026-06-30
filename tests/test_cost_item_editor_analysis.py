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


if __name__ == "__main__":
    unittest.main()
