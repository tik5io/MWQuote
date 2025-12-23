# infrastructure/persistence.py
import json
import dataclasses
from enum import Enum
from typing import Any, Dict
from domain.project import Project
from domain.operation import Operation
from domain.cost import CostItem, CostType, PricingType, PricingStructure, PricingTier

class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if isinstance(o, Enum):
            return o.value
        return super().default(o)

class PersistenceService:
    @staticmethod
    def project_to_json(project: Project) -> str:
        """Serialize project to JSON string."""
        return json.dumps(project, cls=EnhancedJSONEncoder, indent=4)

    @staticmethod
    def save_project(project: Project, filepath: str):
        """Save project to file."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(project, f, cls=EnhancedJSONEncoder, indent=4)

    @staticmethod
    def load_project(filepath: str) -> Project:
        """Load project from file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return PersistenceService.project_from_dict(data)

    @staticmethod
    def project_from_dict(data: Dict[str, Any]) -> Project:
        """Reconstruct Project from dictionary."""
        operations = []
        for op_data in data.get('operations', []):
            costs = {}
            for cost_name, cost_data in op_data.get('costs', {}).items():
                # Reconstruct PricingStructure
                p_data = cost_data.get('pricing', {})
                tiers = []
                for t_data in p_data.get('tiers', []):
                    # Ensure fixed_price is present in tier
                    tiers.append(PricingTier(
                        min_quantity=t_data['min_quantity'],
                        max_quantity=t_data.get('max_quantity'),
                        fixed_price=t_data.get('fixed_price', 0.0),
                        unit_price=t_data.get('unit_price', 0.0),
                        description=t_data.get('description', "")
                    ))
                
                pricing = PricingStructure(
                    pricing_type=PricingType(p_data['pricing_type']),
                    fixed_price=p_data.get('fixed_price', 0.0),
                    unit_price=p_data.get('unit_price', 0.0),
                    unit=p_data.get('unit', "pièce"),
                    tiers=tiers
                )
                
                # Reconstruct CostItem
                cost = CostItem(
                    name=cost_data['name'],
                    cost_type=CostType(cost_data['cost_type']),
                    pricing=pricing,
                    supplier_quote_ref=cost_data.get('supplier_quote_ref'),
                    comment=cost_data.get('comment'),
                    fixed_time=cost_data.get('fixed_time', 0.0),
                    per_piece_time=cost_data.get('per_piece_time', 0.0),
                    margin_percentage=cost_data.get('margin_percentage', 0.0),
                    quantity_multiplier=cost_data.get('quantity_multiplier', 1.0)
                )
                costs[cost_name] = cost
            
            op = Operation(
                code=op_data['code'],
                label=op_data['label'],
                costs=costs,
                total_pieces=op_data.get('total_pieces', 1)
            )
            operations.append(op)
            
        return Project(
            name=data['name'],
            reference=data.get('reference', ""),
            client=data.get('client', ""),
            operations=operations,
            drawing_filename=data.get('drawing_filename'),
            drawing_data=data.get('drawing_data')
        )
