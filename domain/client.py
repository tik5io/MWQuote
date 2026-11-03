# domain/client.py
"""Client (nom + secteur d'activité) et mentions de traçabilité qui en découlent."""
from dataclasses import dataclass
from typing import List

SECTOR_MEDICAL = "Médical"
SECTOR_AERO = "Aéronautique"
SECTOR_OTHER = "Autre"
SECTORS = [SECTOR_MEDICAL, SECTOR_AERO, SECTOR_OTHER]

PROTOTYPE_LABEL = ("Pièce prototype, pas de traçabilité selon ISO 13485 ou 9100 / "
                   "Pas de qualification réalisée sur ce lot")
PROTOTYPE_LINES = [
    "Pièce prototype, pas de traçabilité selon ISO 13485 ou 9100",
    "Pas de qualification réalisée sur ce lot",
]


@dataclass
class Client:
    name: str
    sector: str = SECTOR_OTHER


def normalize_sector(sector) -> str:
    return sector if sector in SECTORS else SECTOR_OTHER


def traceability_mentions(sector: str) -> List[str]:
    """Mentions « Non applicable » selon le secteur du client."""
    sector = normalize_sector(sector)
    lines = []
    if sector != SECTOR_MEDICAL:
        lines.append("Traçabilité et suivi ISO 13485 Non applicable")
    if sector != SECTOR_AERO:
        lines.append("Traçabilité et suivi ISO 9100 Non applicable")
    return lines
