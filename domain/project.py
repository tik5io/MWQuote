# domain/project.py
import copy
import uuid
import os
import datetime
from typing import List, Optional

from .operation import Operation
from .document import Document
from .serie_data import SerieData
from .project_version import ProjectVersion


class Project:
    """
    Un projet MWQuote contient N versions indicées de gamme.
    Chaque version a ses propres opérations, coûts et documents.
    Les propriétés de premier niveau (operations, …) délèguent vers la version courante.
    """

    def __init__(
        self,
        name: str,
        reference: str,
        client: str,
        mwq_uuid: str = "",
        project_date: str = None,
        preview_image: Document = None,
        versions: List[ProjectVersion] = None,
        current_version_index: int = 1,
        # Legacy / convenience args (ignorés si versions est fourni)
        operations: List[Operation] = None,
        documents: List[Document] = None,
        sale_quantities: List[int] = None,
        volume_margin_rates: dict = None,
        serie_data: Optional[SerieData] = None,
        is_prototype: bool = False,
        # Champs obsolètes — acceptés en lecture pour compatibilité fichiers anciens
        export_history: List[dict] = None,
        status: str = None,
        status_dates: dict = None,
        validation_report: dict = None,
        tags: list = None,
    ):
        self.name = name
        self.reference = reference
        self.client = client
        self.mwq_uuid = mwq_uuid
        self.project_date = project_date
        self.preview_image = preview_image
        self.is_prototype: bool = bool(is_prototype)
        self._current_version_index: int = current_version_index
        self.export_history: List[dict] = export_history if export_history is not None else []

        if versions:
            self._versions: List[ProjectVersion] = versions
        else:
            v1 = ProjectVersion(
                version_index=1,
                created_at=datetime.datetime.now().isoformat(),
                operations=operations if operations is not None else [],
                documents=documents if documents is not None else [],
                sale_quantities=sale_quantities if sale_quantities is not None else [1, 10, 50, 100],
                volume_margin_rates=volume_margin_rates if volume_margin_rates is not None else {},
                serie_data=serie_data,
            )
            self._versions = [v1]

    # ------------------------------------------------------------------ #
    # Version management                                                    #
    # ------------------------------------------------------------------ #

    @property
    def versions(self) -> List[ProjectVersion]:
        return self._versions

    @property
    def current_version_index(self) -> int:
        return self._current_version_index

    @property
    def current_version(self) -> ProjectVersion:
        for v in self._versions:
            if v.version_index == self._current_version_index:
                return v
        return self._versions[-1] if self._versions else None

    def switch_to_version(self, version_index: int) -> bool:
        for v in self._versions:
            if v.version_index == version_index:
                self._current_version_index = version_index
                return True
        return False

    def add_version(self, label: str = "") -> ProjectVersion:
        """Crée une nouvelle version en copiant la version courante."""
        new_index = max(v.version_index for v in self._versions) + 1
        new_version = copy.deepcopy(self.current_version)
        new_version.version_index = new_index
        new_version.label = label
        new_version.created_at = datetime.datetime.now().isoformat()
        new_version.created_from_version = self._current_version_index
        self._versions.append(new_version)
        return new_version

    def split_version_to_project(self, version_index: int) -> 'Project':
        """Crée un nouveau projet autonome à partir d'une version."""
        version = next((v for v in self._versions if v.version_index == version_index), None)
        if version is None:
            raise ValueError(f"Version {version_index} introuvable")

        new_v = copy.deepcopy(version)
        new_v.version_index = 1
        new_v.created_from_version = None

        new_project = Project(
            name=self.name,
            reference=self.reference,
            client=self.client,
            mwq_uuid=str(uuid.uuid4()),
            project_date=self.project_date,
            preview_image=copy.deepcopy(self.preview_image),
            versions=[new_v],
            current_version_index=1,
        )
        new_project._regenerate_document_filenames(new_project.mwq_uuid)
        return new_project

    # ------------------------------------------------------------------ #
    # Delegate properties → version courante                               #
    # ------------------------------------------------------------------ #

    @property
    def operations(self) -> List[Operation]:
        return self.current_version.operations

    @operations.setter
    def operations(self, value: List[Operation]):
        self.current_version.operations = value

    @property
    def documents(self) -> List[Document]:
        return self.current_version.documents

    @documents.setter
    def documents(self, value: List[Document]):
        self.current_version.documents = value

    @property
    def sale_quantities(self) -> List[int]:
        return self.current_version.sale_quantities

    @sale_quantities.setter
    def sale_quantities(self, value: List[int]):
        self.current_version.sale_quantities = value

    @property
    def volume_margin_rates(self) -> dict:
        return self.current_version.volume_margin_rates

    @volume_margin_rates.setter
    def volume_margin_rates(self, value: dict):
        self.current_version.volume_margin_rates = value

    @property
    def serie_data(self) -> Optional[SerieData]:
        return self.current_version.serie_data

    @serie_data.setter
    def serie_data(self, value: Optional[SerieData]):
        self.current_version.serie_data = value

    # Champs obsolètes — propriétés fantômes pour compatibilité code existant
    @property
    def tags(self) -> list:
        return ["Prototype"] if self.is_prototype else []

    @tags.setter
    def tags(self, value: list):
        pass  # ignored

    @property
    def status(self) -> str:
        return ""

    @status.setter
    def status(self, value: str):
        pass  # ignored

    @property
    def status_dates(self) -> dict:
        return {}

    @status_dates.setter
    def status_dates(self, value: dict):
        pass  # ignored

    @property
    def validation_report(self) -> dict:
        return {}

    @validation_report.setter
    def validation_report(self, value: dict):
        pass  # ignored

    # ------------------------------------------------------------------ #
    # Legacy compatibility properties                                       #
    # ------------------------------------------------------------------ #

    @property
    def drawing_filename(self):
        return self.documents[0].filename if self.documents else None

    @property
    def drawing_data(self):
        return self.documents[0].data if self.documents else None

    @property
    def display_name(self) -> str:
        if self.reference and self.reference.strip():
            return self.reference.strip()
        if self.name and self.name.strip():
            return self.name.strip()
        return "Nouveau Projet"

    # ------------------------------------------------------------------ #
    # Business methods                                                      #
    # ------------------------------------------------------------------ #

    def total_price(self, quantity: int = None) -> float:
        base_price = sum(op.total_with_margins(quantity) for op in self.operations)
        rate = self.volume_margin_rates.get(quantity, 1.0) if quantity is not None else 1.0
        return base_price * rate

    def add_operation(self, operation: Operation) -> None:
        self.operations.append(operation)

    def move_operation(self, index: int, direction: int) -> bool:
        new_index = index + direction
        if 0 <= new_index < len(self.operations):
            self.operations[index], self.operations[new_index] = (
                self.operations[new_index], self.operations[index]
            )
            return True
        return False

    def clone(self) -> 'Project':
        """Retourne une copie profonde avec un nouveau UUID."""
        new_project = copy.deepcopy(self)
        new_uuid = str(uuid.uuid4())
        new_project.mwq_uuid = new_uuid
        new_project.export_history = []
        new_project._regenerate_document_filenames(new_uuid)
        return new_project

    def _regenerate_document_filenames(self, new_uuid: str):
        """Régénère les noms de fichiers documents avec le nouvel UUID."""
        if self.preview_image and self.preview_image.filename:
            base_name = os.path.basename(self.preview_image.filename)
            self.preview_image.filename = f"{new_uuid}_{base_name}"

        for version in self._versions:
            for doc in version.documents:
                if doc.filename:
                    base_name = os.path.basename(doc.filename)
                    doc.filename = f"{new_uuid}_{base_name}"
            for op in version.operations:
                for cost_item in op.costs.values():
                    for doc in cost_item.documents:
                        if doc.filename:
                            base_name = os.path.basename(doc.filename)
                            doc.filename = f"{new_uuid}_{base_name}"
