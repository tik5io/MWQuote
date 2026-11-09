# domain/client.py
"""Client (nom seul) et domaines d'application du PROJET, avec les mentions de traçabilité qui en découlent.

Un client peut travailler dans plusieurs domaines à la fois (médical ET aéronautique) : le domaine
d'application n'est donc pas une propriété du client mais du projet, où on le coche (un, les deux,
ou aucun). Voir `Project.sectors`.
"""
from dataclasses import dataclass
from typing import Iterable, List, Union

SECTOR_MEDICAL = "Médical"
SECTOR_AERO = "Aéronautique"
SECTORS = [SECTOR_MEDICAL, SECTOR_AERO]
# Norme de traçabilité associée à chaque secteur : c'est ce que l'on coche (« suit-on cette norme ? »)
SECTOR_NORMS = {SECTOR_MEDICAL: "ISO 13485", SECTOR_AERO: "ISO 9100"}

MENTION_FOLLOWED = "Traçabilité et suivi {norm} Applicable"
MENTION_NOT_FOLLOWED = "Traçabilité et suivi {norm} Non applicable"

PROTOTYPE_LABEL = ("Pièce prototype, pas de traçabilité selon ISO 13485 ou 9100 / "
                   "Pas de qualification réalisée sur ce lot")
PROTOTYPE_LINES = [
    "Pièce prototype, pas de traçabilité selon ISO 13485 ou 9100",
    "Pas de qualification réalisée sur ce lot",
]


@dataclass
class Client:
    name: str


def normalize_sectors(sectors: Union[None, str, Iterable[str]]) -> List[str]:
    """Liste des domaines d'application, sans doublon, dans l'ordre de SECTORS.

    Accepte aussi une chaîne seule (ancien format : un secteur par client). Les anciennes
    valeurs « Autre » ou vides, et toute valeur inconnue, donnent « aucun domaine ».
    """
    if not sectors:
        return []
    if isinstance(sectors, str):
        sectors = [sectors]
    wanted = set(sectors)
    return [s for s in SECTORS if s in wanted]


def traceability_mentions(sectors: Union[None, str, Iterable[str]]) -> List[str]:
    """Une mention par norme : « Applicable » pour celles que l'on suit, « Non applicable » pour les autres.

    Les deux cas sont dits explicitement (une norme suivie est affirmée, pas seulement sous-entendue).
    Ordre fixe : ISO 13485 puis ISO 9100.
    """
    sectors = normalize_sectors(sectors)
    return [(MENTION_FOLLOWED if sector in sectors else MENTION_NOT_FOLLOWED).format(norm=SECTOR_NORMS[sector])
            for sector in SECTORS]
