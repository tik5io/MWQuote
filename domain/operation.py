from dataclasses import dataclass, field
from typing import Dict
from .cost import CostItem, CostType, PricingStructure, PricingType

SUBCONTRACTING_TYPOLOGY = "Sous-traitance"

@dataclass
class Operation:
    code: str
    label: str
    typology: str = ""
    comment: str = ""
    costs: Dict[str, CostItem] = field(default_factory=dict)
    total_pieces: int = 1  # Number of pieces for per-piece calculations

    def _get_active_costs(self):
        """Returns filtered costs if subcontracting, else all costs."""
        if self.typology == SUBCONTRACTING_TYPOLOGY:
            return [c for c in self.costs.values() if c.is_active]
        return list(self.costs.values())

    def total_cost(self, quantity: int = None) -> float:
        """Calculate the unit base cost (aggregate of all cost items)"""
        q = quantity if quantity is not None else self.total_pieces
        from .calculator import Calculator
        return sum(Calculator.calculate_item(item, q).unit_cost_converted for item in self._get_active_costs())

    def total_with_margins(self, quantity: int = None) -> float:
        """Calculate the unit sale price (aggregate of all cost items with their margins)"""
        q = quantity if quantity is not None else self.total_pieces
        from .calculator import Calculator
        return sum(Calculator.calculate_item(item, q).unit_sale_price for item in self._get_active_costs())

    def calculate_sale_components(self, quantity: int = None) -> (float, float):
        """Calculate (fixed_total, variable_total) sale prices for the operation"""
        q = quantity if quantity is not None else self.total_pieces
        total_f = 0.0
        total_v = 0.0
        for item in self._get_active_costs():
            f, v = item.calculate_sale_components(q)
            total_f += f
            total_v += v
        return total_f, total_v

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

    def move_cost(self, cost_name: str, direction: int) -> bool:
        """direction: -1 for up, 1 for down"""
        keys = list(self.costs.keys())
        try:
            idx = keys.index(cost_name)
            new_idx = idx + direction
            if 0 <= new_idx < len(keys):
                keys[idx], keys[new_idx] = keys[new_idx], keys[idx]
                # Rebuild dict to preserve order
                new_costs = {k: self.costs[k] for k in keys}
                self.costs = new_costs
                return True
        except ValueError:
            pass
        return False

    def rename_cost(self, old_name: str, new_name: str) -> bool:
        """Safely rename a cost item and update the dictionary key while preserving order."""
        if old_name not in self.costs:
            return False
        if new_name == old_name:
            return True
        if new_name in self.costs or not new_name:
            return False

        # Rebuild dict to preserve order
        new_costs = {}
        for k, v in self.costs.items():
            if k == old_name:
                v.name = new_name
                new_costs[new_name] = v
            else:
                new_costs[k] = v
        self.costs = new_costs
        return True
