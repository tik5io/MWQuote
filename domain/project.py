# domain/project.py
from dataclasses import dataclass, field
from typing import List
from .operation import Operation
from .document import Document

@dataclass
class Project:
    name: str
    reference: str
    client: str
    operations: List[Operation] = field(default_factory=list)
    documents: List[Document] = field(default_factory=list)
    project_date: str = None  # ISO format date (YYYY-MM-DD)
    sale_quantities: List[int] = field(default_factory=lambda: [1, 10, 50, 100])
    tags: List[str] = field(default_factory=list)

    # Milestones & Tracking
    status: str = "En construction" # options: "En construction", "Finalisée", "Transmise"
    status_dates: dict = field(default_factory=dict) # key: status, value: ISO date
    export_history: List[dict] = field(default_factory=list) # [{ "devis_ref": str, "date": str }]

    # Pricing parameters
    volume_margin_rates: dict = field(default_factory=dict)  # dict {quantity: rate}

    @property
    def drawing_filename(self):
        """Legacy compatibility: returns the first document filename."""
        return self.documents[0].filename if self.documents else None

    @property
    def drawing_data(self):
        """Legacy compatibility: returns the first document data."""
        return self.documents[0].data if self.documents else None

    def total_price(self, quantity: int = None) -> float:
        """Calcule le prix total unitaire avec le taux de marge sur volume."""
        base_price = sum(op.total_with_margins(quantity) for op in self.operations)
        rate = self.volume_margin_rates.get(quantity, 1.0) if quantity is not None else 1.0
        return base_price * rate

    def add_operation(self, operation: Operation) -> None:
        self.operations.append(operation)

    def move_operation(self, index: int, direction: int) -> bool:
        """direction: -1 for up, 1 for down"""
        new_index = index + direction
        if 0 <= new_index < len(self.operations):
            self.operations[index], self.operations[new_index] = self.operations[new_index], self.operations[index]
            return True
        return False

    def clone(self):
        """Returns a deep copy of the project with reset milestones."""
        import copy
        new_project = copy.deepcopy(self)
        new_project.status = "En construction"
        new_project.status_dates = {}
        return new_project
