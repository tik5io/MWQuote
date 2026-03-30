# domain/project.py
from dataclasses import dataclass, field
from typing import List
import uuid
from .operation import Operation
from .document import Document

@dataclass
class Project:
    name: str
    reference: str
    client: str
    mwq_uuid: str = ""
    operations: List[Operation] = field(default_factory=list)
    documents: List[Document] = field(default_factory=list)
    project_date: str = None  # ISO format date (YYYY-MM-DD)
    sale_quantities: List[int] = field(default_factory=lambda: [1, 10, 50, 100])
    tags: List[str] = field(default_factory=list)
    preview_image: Document = None

    # Milestones & Tracking
    status: str = "En construction" # options: "En construction", "Finalisée", "Transmise"
    status_dates: dict = field(default_factory=dict) # key: status, value: ISO date
    export_history: List[dict] = field(default_factory=list) # [{ "devis_ref": str, "date": str }]

    # Pricing parameters
    volume_margin_rates: dict = field(default_factory=dict)  # dict {quantity: rate}
    # Validation/diagnostic report (persisted)
    validation_report: dict = field(default_factory=dict)

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
        """Returns a deep copy of the project with reset tracking data."""
        import copy
        new_project = copy.deepcopy(self)
        # A duplicate must have a new UUID context to avoid any linkage/confusion.
        new_uuid = str(uuid.uuid4())
        new_project.mwq_uuid = new_uuid
        new_project.status = "En construction"
        new_project.status_dates = {}
        # Reset XLSX export history so duplicated project restarts at sub-version index 1.
        new_project.export_history = []
        
        # Regenerate document filenames with new UUID to avoid conflicts
        self._regenerate_document_filenames(new_project, new_uuid)
        
        return new_project

    def _regenerate_document_filenames(self, project, new_uuid: str):
        """Regenerate all document filenames to include the new UUID, preventing conflicts."""
        import os
        
        # Regenerate project documents
        for doc in project.documents:
            if doc.filename:
                # Keep original name as part of the filename but prepend UUID
                base_name = os.path.basename(doc.filename)
                doc.filename = f"{new_uuid}_{base_name}"
        
        # Regenerate project preview image filename if present
        if project.preview_image and project.preview_image.filename:
            base_name = os.path.basename(project.preview_image.filename)
            project.preview_image.filename = f"{new_uuid}_{base_name}"

        # Regenerate operation cost documents
        for op in project.operations:
            for cost_item in op.costs.values():
                for doc in cost_item.documents:
                    if doc.filename:
                        base_name = os.path.basename(doc.filename)
                        doc.filename = f"{new_uuid}_{base_name}"
