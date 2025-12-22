# domain/project.py
from dataclasses import dataclass, field
from typing import List
from .operation import Operation

@dataclass
class Project:
    name: str
    reference: str
    client: str
    operations: List[Operation] = field(default_factory=list)

    def total_price(self) -> float:
        return sum(op.total_with_margins() for op in self.operations)

    def add_operation(self, operation: Operation) -> None:
        self.operations.append(operation)
