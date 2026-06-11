# domain/project_version.py
from dataclasses import dataclass, field
from typing import List, Optional
import datetime
from .operation import Operation
from .document import Document
from .serie_data import SerieData


@dataclass
class ProjectVersion:
    version_index: int
    label: str = ""
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    created_from_version: Optional[int] = None

    operations: List[Operation] = field(default_factory=list)
    documents: List[Document] = field(default_factory=list)  # Plans de la pièce
    sale_quantities: List[int] = field(default_factory=lambda: [1, 10, 50, 100])
    volume_margin_rates: dict = field(default_factory=dict)
    status: str = "En construction"
    status_dates: dict = field(default_factory=dict)
    validation_report: dict = field(default_factory=dict)
    serie_data: Optional[SerieData] = None
