# domain/phase.py
"""Configuration de vente d'une version de gamme.

Une version (V1, V2…) porte la gamme ET une configuration (`Phase`) : type de
calcul (Taux horaire = LOT, Décomposé = SERIE), quantités ou volume annuel,
coefficients de marge volume, facturation de l'outillage et, en Décomposé, ses
données SerieData. Vendre la même gamme autrement = créer une nouvelle version.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .serie_data import SerieData


class PhaseKind(Enum):
    LOT = "Lot"      # calcul par quantité commandée (onglet Tarif de Vente)
    SERIE = "Série"  # calcul volume annuel / capacité (onglet Production Série)

    @property
    def calc_label(self) -> str:
        """Libellé « type de calcul » présenté à l'utilisateur.

        Le modèle de données garde Lot / Série (compat fichiers) ; l'interface
        parle désormais de typologie de calcul.
        """
        return "Taux horaire" if self == PhaseKind.LOT else "Décomposé"


class ToolingBilling(Enum):
    REINVOICED = "Refacturé"  # bloc OUTILLAGE de l'offre, hors prix pièce
    AMORTIZED = "Amorti"      # intégré au prix pièce


def default_tooling_billing(kind: PhaseKind) -> ToolingBilling:
    return ToolingBilling.AMORTIZED if kind == PhaseKind.SERIE else ToolingBilling.REINVOICED


@dataclass
class Phase:
    phase_id: str
    label: str
    kind: PhaseKind = PhaseKind.LOT
    sale_quantities: List[int] = field(default_factory=lambda: [1, 10, 50, 100])
    volume_margin_rates: dict = field(default_factory=dict)
    tooling_billing: Optional[ToolingBilling] = None  # None = défaut selon kind
    serie_data: Optional[SerieData] = None            # uniquement si kind == SERIE

    @property
    def is_serie(self) -> bool:
        return self.kind == PhaseKind.SERIE

    @property
    def effective_tooling_billing(self) -> ToolingBilling:
        # Règle métier : en Taux horaire (Lot), l'outillage est TOUJOURS refacturé
        # séparément à la commande — jamais amorti. L'amortissement n'existe qu'en
        # Décomposé (Série). Un éventuel réglage « Amorti » est ignoré en Lot.
        if self.kind == PhaseKind.LOT:
            return ToolingBilling.REINVOICED
        return self.tooling_billing or default_tooling_billing(self.kind)

    @property
    def display_label(self) -> str:
        return self.label or self.kind.value


@dataclass(frozen=True)
class PhaseContext:
    """Contexte de calcul transmis aux opérations (non persisté)."""
    phase_id: str
    kind: PhaseKind
    tooling_billing: ToolingBilling

    @staticmethod
    def of(phase: Phase) -> "PhaseContext":
        return PhaseContext(phase.phase_id, phase.kind, phase.effective_tooling_billing)
