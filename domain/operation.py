from dataclasses import dataclass, field
from typing import Dict
from .cost import CostItem, CostType, PricingStructure, PricingType

@dataclass
class Operation:
    code: str
    label: str
    costs: Dict[str, CostItem] = field(default_factory=dict)
    total_pieces: int = 1  # Number of pieces for per-piece calculations

    def total_cost(self, quantity: int = None) -> float:
        """Calculate total cost including materials, subcontracting, internal operations"""
        q = quantity if quantity is not None else self.total_pieces
        base_cost = sum(item.calculate_value(q) for item in self.costs.values()
                       if item.cost_type != CostType.MARGIN)
        return base_cost

    def total_with_margins(self, quantity: int = None) -> float:
        """Calculate total cost including margins"""
        q = quantity if quantity is not None else self.total_pieces
        base_cost = self.total_cost(q)
        total_margin = sum(item.margin_percentage / 100 * base_cost
                          for item in self.costs.values()
                          if item.cost_type == CostType.MARGIN)
        return base_cost + total_margin

    def add_cost(self, name: str, cost_type: CostType, pricing_type: PricingType = PricingType.PER_UNIT, **kwargs):
        """Add a cost item with pricing structure"""
        pricing = PricingStructure(pricing_type=pricing_type, **kwargs)
        cost_item = CostItem(name=name, cost_type=cost_type, pricing=pricing, **kwargs)
        self.costs[name] = cost_item

    def update_cost(self, name: str, **kwargs):
        """Update cost item parameters"""
        if name in self.costs:
            for key, value in kwargs.items():
                if hasattr(self.costs[name], key):
                    setattr(self.costs[name], key, value)
