# domain/project.py
import copy
import uuid
from contextlib import contextmanager
import os
import datetime
from typing import List, Optional

from .operation import Operation
from .document import Document
from .serie_data import SerieData
from .project_version import ProjectVersion, build_lot_phase, build_serie_phase
from .phase import Phase, PhaseKind, PhaseContext


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
        project_folder: str = "",
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
        self.project_folder = project_folder or ""
        self.preview_image = preview_image
        self.is_prototype: bool = bool(is_prototype)
        self._current_version_index: int = current_version_index
        self.export_history: List[dict] = export_history if export_history is not None else []

        if versions:
            self._versions: List[ProjectVersion] = versions
        else:
            now = datetime.datetime.now().isoformat()
            v1 = ProjectVersion(
                version_index=1,
                created_at=now,
                operations=operations if operations is not None else [],
                documents=documents if documents is not None else [],
                phase=build_lot_phase(sale_quantities, volume_margin_rates),
            )
            self._versions = [v1]
            if serie_data is not None:
                # Ancien chiffrage série : devient une version Décomposé distincte
                # (copie de la gamme), la version 1 restant le Taux horaire.
                v2 = copy.deepcopy(v1)
                v2.version_index = 2
                v2.label = "Série"
                v2.created_from_version = 1
                v2.phase = build_serie_phase(serie_data)
                self._versions.append(v2)

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

    def get_version(self, version_index: int):
        return next((v for v in self._versions if v.version_index == version_index), None)

    def add_version(self, label: str = "", base_version_index: int = None) -> ProjectVersion:
        """Crée une nouvelle version en copiant `base_version_index` (par défaut la version courante)."""
        base = self.get_version(base_version_index) if base_version_index is not None else None
        base = base or self.current_version
        new_index = max(v.version_index for v in self._versions) + 1
        new_version = copy.deepcopy(base)
        new_version.version_index = new_index
        new_version.label = label
        new_version.created_at = datetime.datetime.now().isoformat()
        new_version.created_from_version = base.version_index
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
            project_folder=self.project_folder,
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
        ops = self.current_version.operations
        ctx = PhaseContext.of(self.current_version.current_phase)
        for op in ops:
            op.set_phase_context(ctx)
        return ops

    @operations.setter
    def operations(self, value: List[Operation]):
        self.current_version.operations = value

    @property
    def documents(self) -> List[Document]:
        return self.current_version.documents

    @documents.setter
    def documents(self, value: List[Document]):
        self.current_version.documents = value

    # ------------------------------------------------------------------ #
    # Configuration de vente de la version courante (ex-« phase »)          #
    # ------------------------------------------------------------------ #
    # Une version porte une seule configuration : type de calcul, quantités
    # (plage de lots ou volume annuel), coefficients, facturation outillage.

    @property
    def phases(self) -> List[Phase]:
        return self.current_version.phases

    @property
    def current_phase(self) -> Phase:
        return self.current_version.current_phase

    def switch_to_phase(self, phase_id: str) -> bool:
        """Compat : une version n'a qu'une configuration, rien à basculer."""
        return self.current_version.get_phase(phase_id) is not None

    def add_version_variant(self, label: str, kind: PhaseKind, sale_quantities: List[int] = None,
                            annual_volume: int = None, base_version_index: int = None) -> ProjectVersion:
        """Nouvelle version = copie d'une version existante, vendue autrement.

        Même gamme, autres quantités et/ou autre type de calcul (Taux horaire ↔
        Décomposé). `base_version_index` désigne la version copiée (par défaut la
        courante) ; elle n'est pas modifiée.

        Version Décomposé : la structure et les temps de la version de départ sont
        repris AU MOMENT DE LA COPIE (postes machine : temps de cycle, taux) ; le
        lien avec la version d'origine est ensuite rompu, les deux évoluent
        indépendamment.
        """
        version = self.add_version(label, base_version_index=base_version_index)
        version.configure(kind, sale_quantities=sale_quantities, annual_volume=annual_volume)
        if kind == PhaseKind.SERIE and version.phase.serie_data is not None:
            version.phase.serie_data.sync_from_project(self, phase=version.phase, operations=version.operations)
        return version

    @contextmanager
    def calculation_phase(self, phase_id: str = None):
        """Contexte de calcul de la version courante (une seule configuration)."""
        ctx = PhaseContext.of(self.current_version.current_phase)
        for op in self.current_version.operations:
            op.set_phase_context(ctx)
        yield

    # Raccourcis : quantités / coefficients / données Décomposé de la version courante.

    @property
    def sale_quantities(self) -> List[int]:
        return self.current_version.sale_quantities

    @sale_quantities.setter
    def sale_quantities(self, value: List[int]):
        self.current_version.phase.sale_quantities = value

    @property
    def volume_margin_rates(self) -> dict:
        return self.current_version.volume_margin_rates

    @volume_margin_rates.setter
    def volume_margin_rates(self, value: dict):
        self.current_version.phase.volume_margin_rates = value

    @property
    def serie_data(self) -> Optional[SerieData]:
        return self.current_version.serie_data

    @serie_data.setter
    def serie_data(self, value: Optional[SerieData]):
        if value is None:
            return  # une version Décomposé garde ses données : on supprime la version, pas les données
        version = self.current_version
        if version.phase.kind != PhaseKind.SERIE:
            raise ValueError("Une version Taux horaire n'a pas de données Décomposé : "
                             "créer une version Décomposé (add_version_variant).")
        version.phase.serie_data = value

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
        """Prix de vente unitaire de la phase Lot de référence (la courante si Lot)."""
        version = self.current_version
        lot = version.lot_phase
        ops = version.operations
        for op in ops:
            op.set_phase_context(PhaseContext.of(lot))
        try:
            base_price = sum(op.total_with_margins(quantity) for op in ops)
        finally:
            current = PhaseContext.of(version.current_phase)
            for op in ops:
                op.set_phase_context(current)
        rate = lot.volume_margin_rates.get(quantity, 1.0) if quantity is not None else 1.0
        return base_price * rate

    def is_version_frozen(self, version_index: int = None) -> bool:
        """La gamme de la version est figée dès qu'une offre à indice a été émise dessus."""
        from . import offers
        idx = self._current_version_index if version_index is None else version_index
        return offers.is_version_frozen(self.export_history, idx)

    def version_frozen_by(self, version_index: int = None):
        from . import offers
        idx = self._current_version_index if version_index is None else version_index
        return offers.frozen_by(self.export_history, idx)

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
