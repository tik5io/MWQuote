# infrastructure/persistence.py
import json
import dataclasses
from enum import Enum
from typing import Any, Dict
from domain.project import Project
from domain.operation import Operation
from domain.cost import CostItem, CostType, PricingType, PricingStructure, PricingTier, ConversionType
from domain.document import Document

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
                ctype_val = cost_data.get('cost_type')
                if ctype_val == "Marge":
                     # Skip legacy margin items as they are now integrated into other costs
                     continue
                
                # Documents migration/reconstruction
                docs = []
                for d_data in cost_data.get('documents', []):
                    docs.append(Document(filename=d_data['filename'], data=d_data['data']))
                
                # Backward compatibility migration
                if not docs and cost_data.get('supplier_quote_filename') and cost_data.get('supplier_quote_data'):
                    docs.append(Document(
                        filename=cost_data['supplier_quote_filename'],
                        data=cost_data['supplier_quote_data']
                    ))

                cost = CostItem(
                    name=cost_data['name'],
                    cost_type=CostType(ctype_val),
                    pricing=pricing,
                    supplier_quote_ref=cost_data.get('supplier_quote_ref'),
                    documents=docs,
                    comment=cost_data.get('comment'),
                    fixed_time=cost_data.get('fixed_time', 0.0),
                    per_piece_time=cost_data.get('per_piece_time', 0.0),
                    hourly_rate=cost_data.get('hourly_rate', 0.0),
                    margin_rate=cost_data.get('margin_rate', cost_data.get('margin_percentage', 0.0)),
                    conversion_factor=cost_data.get('conversion_factor', cost_data.get('quantity_multiplier', 1.0)),
                    conversion_type=ConversionType(cost_data.get('conversion_type', "Multiplier")),
                    quantity_per_piece=cost_data.get('quantity_per_piece', 1.0),
                    is_active=cost_data.get('is_active', True)
                )
                costs[cost_name] = cost
            
            op = Operation(
                code=op_data['code'],
                label=op_data['label'],
                typology=op_data.get('typology', ""),
                comment=op_data.get('comment', ""),
                costs=costs,
                total_pieces=op_data.get('total_pieces', 1)
            )
            operations.append(op)
            
        # Project Documents migration/reconstruction
        proj_docs = []
        for d_data in data.get('documents', []):
            proj_docs.append(Document(filename=d_data['filename'], data=d_data['data']))
        
        # Backward compatibility
        if not proj_docs and data.get('drawing_filename') and data.get('drawing_data'):
            proj_docs.append(Document(
                filename=data['drawing_filename'],
                data=data['drawing_data']
            ))

        return Project(
            name=data['name'],
            reference=data.get('reference', ""),
            client=data.get('client', ""),
            operations=operations,
            documents=proj_docs,
            project_date=data.get('project_date'),
            sale_quantities=data.get('sale_quantities', [1, 10, 50, 100]),
            tags=data.get('tags', []),
            status=data.get('status', "En construction"),
            status_dates=data.get('status_dates', {})
        )
