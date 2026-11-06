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
    """Mentions « Non applicable » selon les domaines du projet : une norme absente est non applicable."""
    sectors = normalize_sectors(sectors)
    lines = []
    if SECTOR_MEDICAL not in sectors:
        lines.append("Traçabilité et suivi ISO 13485 Non applicable")
    if SECTOR_AERO not in sectors:
        lines.append("Traçabilité et suivi ISO 9100 Non applicable")
    return lines
