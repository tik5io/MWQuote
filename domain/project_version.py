# domain/project_version.py
"""Version de gamme.

Modèle fusionné : une version = la gamme (opérations Interne / Sous-traitance et
leurs outillages) + UNE configuration de vente portée par `phase` (type de
calcul Taux horaire | Décomposé, quantités ou volume annuel, coefficients,
facturation de l'outillage). Pour vendre la même gamme autrement (autres
quantités, autre mode de calcul), on crée une nouvelle version.

L'objet Phase est conservé comme « configuration de calcul » de la version ;
les propriétés `phases`, `current_phase`… restent exposées (une seule phase)
pour que le code existant fonctionne pendant la transition.
"""
from dataclasses import dataclass, field
from typing import List, Optional
import datetime
from .operation import Operation
from .document import Document
from .serie_data import SerieData
from .phase import Phase, PhaseKind

DEFAULT_LOT_PHASE_ID = "ph1"
DEFAULT_SERIE_PHASE_ID = "ph2"


def build_lot_phase(sale_quantities: Optional[List[int]] = None,
                    volume_margin_rates: Optional[dict] = None,
                    label: str = "Tarif") -> Phase:
    """Configuration Taux horaire (ex-phase Lot)."""
    return Phase(
        phase_id=DEFAULT_LOT_PHASE_ID,
        label=label,
        kind=PhaseKind.LOT,
        sale_quantities=list(sale_quantities) if sale_quantities is not None else [1, 10, 50, 100],
        volume_margin_rates=dict(volume_margin_rates) if volume_margin_rates is not None else {},
    )


def build_serie_phase(serie_data: Optional[SerieData] = None, label: str = "Série") -> Phase:
    """Configuration Décomposé (ex-phase Série)."""
    return Phase(
        phase_id=DEFAULT_LOT_PHASE_ID,
        label=label,
        kind=PhaseKind.SERIE,
        sale_quantities=[],
        serie_data=serie_data if serie_data is not None else SerieData.new_for_phase(),
    )


@dataclass
class ProjectVersion:
    version_index: int
    label: str = ""
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    created_from_version: Optional[int] = None

    operations: List[Operation] = field(default_factory=list)
    documents: List[Document] = field(default_factory=list)  # Plans de la pièce
    phase: Phase = field(default_factory=build_lot_phase)

    # ------------------------------------------------------- compat « phases »

    @property
    def phases(self) -> List[Phase]:
        return [self.phase]

    @property
    def current_phase(self) -> Phase:
        return self.phase

    @property
    def current_phase_id(self) -> str:
        return self.phase.phase_id

    def get_phase(self, phase_id: Optional[str]) -> Optional[Phase]:
        return self.phase if phase_id == self.phase.phase_id else None

    @property
    def lot_phase(self) -> Phase:
        """Configuration de la version (quantités / coefficients lus par le code existant)."""
        return self.phase

    @property
    def serie_phase(self) -> Optional[Phase]:
        return self.phase if self.phase.kind == PhaseKind.SERIE else None

    @property
    def is_serie(self) -> bool:
        return self.phase.kind == PhaseKind.SERIE

    # ---------------------------------------------------------------- raccourcis

    @property
    def sale_quantities(self) -> List[int]:
        """Taux horaire : la plage de lots. Décomposé : le volume annuel."""
        if self.phase.kind == PhaseKind.SERIE:
            sd = self.phase.serie_data
            return [int(sd.annual_volume)] if sd and sd.annual_volume else []
        return self.phase.sale_quantities

    @property
    def volume_margin_rates(self) -> dict:
        return self.phase.volume_margin_rates

    @property
    def serie_data(self) -> Optional[SerieData]:
        return self.phase.serie_data if self.phase.kind == PhaseKind.SERIE else None

    @property
    def display_mode(self) -> str:
        return self.phase.kind.calc_label

    def describe(self) -> str:
        """Résumé court : « Taux horaire · 5 / 25 / 100 pc » ou « Décomposé · 100 000 / an »."""
        if self.phase.kind == PhaseKind.SERIE:
            sd = self.phase.serie_data
            vol = f"{int(sd.annual_volume):,}".replace(",", " ") if sd else "—"
            return f"{self.display_mode} · {vol} / an"
        qtys = sorted(self.phase.sale_quantities or [])
        return f"{self.display_mode} · {' / '.join(map(str, qtys)) if qtys else '—'} pc"

    # ---------------------------------------------------------------- configuration

    def configure(self, kind: PhaseKind, sale_quantities: Optional[List[int]] = None,
                  annual_volume: Optional[int] = None) -> None:
        """Change le mode de calcul / les quantités de la version (gamme inchangée)."""
        phase = self.phase
        phase.kind = kind
        if kind == PhaseKind.SERIE:
            if phase.serie_data is None:
                phase.serie_data = SerieData.new_for_phase()
            if annual_volume:
                phase.serie_data.annual_volume = int(annual_volume)
            phase.sale_quantities = []
        else:
            phase.serie_data = None           # un Taux horaire n'a pas de données Décomposé
            if sale_quantities is not None:
                phase.sale_quantities = sorted({int(q) for q in sale_quantities if int(q) > 0}) or [1]
            elif not phase.sale_quantities:
                phase.sale_quantities = [1, 10, 50, 100]
