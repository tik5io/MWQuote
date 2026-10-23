# domain/offers.py
"""Offres et indices d'offre.

Une offre = un numéro de devis (devis_ref) émis sur une version de gamme. Chaque
ajustement des paramètres de vente (quantités, coefficients) donne un nouvel
INDICE de la même offre : A, B, C… Un indice conserve la photo des paramètres de
vente (`coeffs`) pour pouvoir les recharger, et le fichier XLSX remis au client.

Stockage : `Project.export_history`, liste de dicts (déjà lue par le dossier
projet, la recherche et l'index). Champs ajoutés à chaque entrée :
  - revision : indice de l'offre (« A » si absent — anciennes entrées) ;
  - coeffs   : photo des paramètres de vente (absente pour les anciennes entrées).

Une version est FIGÉE dès qu'une offre a été émise dessus : sa gamme n'est plus
modifiable, il faut créer une nouvelle version. Cela vaut aussi pour les offres
antérieures à la gestion des indices (entrées sans `revision`) : elles figent leur
version, restent consultables (fichier XLSX) mais sans coefficients, et sont
signalées par un avertissement de compatibilité (`is_legacy`).
"""
from typing import Dict, List, Optional

FIRST_REVISION = "A"


def revision_of(entry: dict) -> str:
    return entry.get("revision") or FIRST_REVISION


def is_legacy(entry: dict) -> bool:
    """Offre antérieure à la gestion des indices : pas d'indice ni de coefficients archivés."""
    return not entry.get("revision")


def _revision_index(revision: str) -> int:
    """A=0 … Z=25, AA=26 …"""
    n = 0
    for ch in revision.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _revision_name(index: int) -> str:
    name = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def next_revision(history: List[dict], devis_ref: str) -> str:
    """Prochain indice de l'offre `devis_ref` (A si elle n'existe pas encore)."""
    known = [_revision_index(revision_of(e)) for e in history if e.get("devis_ref") == devis_ref]
    return _revision_name(max(known) + 1) if known else FIRST_REVISION


def snapshot_coefficients(version) -> dict:
    """Photo des paramètres de vente d'une version (de quoi recharger un indice)."""
    phase = version.phase
    if version.is_serie:
        sd = phase.serie_data
        return {"mode": "serie",
                "annual_volume": int(sd.annual_volume) if sd else 0,
                "global_commercial_margin": float(sd.global_commercial_margin) if sd else 0.0}
    quantities = sorted(phase.sale_quantities or [])
    return {"mode": "lot",
            "quantities": quantities,
            "rates": {str(q): float(phase.volume_margin_rates.get(q, 1.0)) for q in quantities}}


def apply_snapshot(version, coeffs: Optional[dict]) -> bool:
    """Recharge dans la version les paramètres de vente d'un indice. False si rien à recharger."""
    if not coeffs:
        return False
    phase = version.phase
    if coeffs.get("mode") == "serie":
        if not version.is_serie or phase.serie_data is None:
            return False
        phase.serie_data.annual_volume = int(coeffs.get("annual_volume", phase.serie_data.annual_volume))
        phase.serie_data.global_commercial_margin = float(
            coeffs.get("global_commercial_margin", phase.serie_data.global_commercial_margin))
        return True
    if version.is_serie:
        return False
    quantities = [int(q) for q in coeffs.get("quantities", [])]
    phase.sale_quantities = quantities
    phase.volume_margin_rates = {int(q): float(r) for q, r in (coeffs.get("rates") or {}).items()}
    return True


def same_coefficients(a: Optional[dict], b: Optional[dict]) -> bool:
    """Deux photos de paramètres de vente sont-elles identiques (tolérance numérique) ?"""
    if not a or not b or a.get("mode") != b.get("mode"):
        return False
    if a.get("mode") == "serie":
        return (a.get("annual_volume") == b.get("annual_volume")
                and abs(a.get("global_commercial_margin", 0) - b.get("global_commercial_margin", 0)) < 1e-9)
    if a.get("quantities") != b.get("quantities"):
        return False
    ra, rb = a.get("rates") or {}, b.get("rates") or {}
    return ra.keys() == rb.keys() and all(abs(ra[k] - rb[k]) < 1e-9 for k in ra)


def group_offers(history: List[dict]) -> List[dict]:
    """[{devis_ref, version_index, entries:[…triées par indice]}] dans l'ordre d'émission."""
    groups: Dict[tuple, dict] = {}
    for entry in history:
        key = (entry.get("version_index", 1), entry.get("devis_ref", ""))
        group = groups.setdefault(key, {"devis_ref": key[1], "version_index": key[0], "entries": []})
        group["entries"].append(entry)
    for group in groups.values():
        group["entries"].sort(key=lambda e: _revision_index(revision_of(e)))
    return list(groups.values())


def is_version_frozen(history: List[dict], version_index: int) -> bool:
    return any(e.get("version_index", 1) == version_index for e in history)


def frozen_by(history: List[dict], version_index: int) -> Optional[str]:
    """Numéro de devis de la première offre qui fige la version (None si libre)."""
    for e in history:
        if e.get("version_index", 1) == version_index:
            return e.get("devis_ref")
    return None


def latest_offer_ref(history: List[dict], version_index: int):
    """Numéro de devis de la dernière offre émise sur la version (None si la version n'a pas d'offre)."""
    refs = [e.get("devis_ref") for e in history or [] if e.get("version_index", 1) == version_index and e.get("devis_ref")]
    return refs[-1] if refs else None
