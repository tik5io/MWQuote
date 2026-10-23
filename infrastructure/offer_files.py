# infrastructure/offer_files.py
"""Ouverture du fichier XLSX d'une offre émise.

Excel refuse d'ouvrir en même temps deux classeurs portant le même NOM, même s'ils
sont dans des dossiers différents. Le nom saisi à l'émission pouvait se répéter ;
la copie temporaire est donc nommée d'après la référence d'offre (unique) et son
indice : `OD261016_004.xlsx`, `OD261016_004-indB.xlsx`.
"""
import base64
import hashlib
import os
import re
import tempfile
from typing import Optional

OFFERS_TEMP_DIR = "MWQuote_offres"


def workbook_name(entry: dict) -> str:
    """Nom de classeur unique d'une offre : référence de devis + indice (A implicite)."""
    ref = re.sub(r'[\\/:*?"<>|\s]+', "_", (entry.get("devis_ref") or "").strip()).strip("_")
    if not ref:                                   # entrée sans référence : empreinte du contenu
        ref = "offre_" + hashlib.sha256((entry.get("xlsx_data_b64") or "").encode()).hexdigest()[:10]
    revision = entry.get("revision")
    suffix = f"-ind{revision}" if revision and revision != "A" else ""
    return f"{ref}{suffix}.xlsx"


def offer_workbook_path(entry: dict, directory: Optional[str] = None) -> str:
    """Écrit (si besoin) le XLSX de l'offre dans un dossier temporaire et retourne son chemin.

    Lève ValueError si l'entrée ne porte aucun fichier. Si le classeur est déjà
    ouvert dans Excel (écriture refusée) : on le réutilise s'il est identique,
    sinon on écrit une variante au nom suffixé d'une empreinte du contenu.
    """
    data = entry.get("xlsx_data_b64")
    if not data:
        raise ValueError("Aucun fichier XLSX stocké pour cette offre.")
    content = base64.b64decode(data)
    folder = directory or os.path.join(tempfile.gettempdir(), OFFERS_TEMP_DIR)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, workbook_name(entry))
    try:
        with open(path, "wb") as f:
            f.write(content)
        return path
    except PermissionError:
        try:
            with open(path, "rb") as f:
                if f.read() == content:
                    return path                   # déjà ouvert, même contenu
        except OSError:
            pass
        digest = hashlib.sha256(content).hexdigest()[:8]
        alt = os.path.join(folder, f"{os.path.splitext(workbook_name(entry))[0]}~{digest}.xlsx")
        with open(alt, "wb") as f:
            f.write(content)
        return alt
