#!/usr/bin/env python3
"""
clipboard_to_png.py
--------------------
Récupère une image depuis le presse-papier et la sauvegarde en PNG.

Usage :
    python clipboard_to_png.py                  # nom automatique horodaté
    python clipboard_to_png.py mon_image.png     # nom explicite
    python clipboard_to_png.py /tmp/capture.png  # chemin complet

Dépendances :
    pip install Pillow
    (sur Linux, installer aussi : sudo apt install xclip  OU  xsel)
"""

import sys
import os
from datetime import datetime


def get_output_path(args: list[str]) -> str:
    """Détermine le chemin de sortie (argument CLI ou nom horodaté)."""
    if len(args) > 1:
        path = args[1]
        # Ajoute l'extension .png si absente
        if not path.lower().endswith(".png"):
            path += ".png"
        return path
    # Nom par défaut : screenshot_YYYYMMDD_HHMMSS.png dans le répertoire courant
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"screenshot_{timestamp}.png"


def grab_image_from_clipboard():
    """
    Tente de récupérer une image depuis le presse-papier.
    Retourne un objet PIL.Image ou lève une exception explicite.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        raise SystemExit(
            "❌  Pillow n'est pas installé.\n"
            "    Lance : pip install Pillow"
        )

    img = ImageGrab.grabclipboard()

    if img is None:
        raise SystemExit(
            "❌  Aucune image trouvée dans le presse-papier.\n"
            "    Assure-toi d'avoir fait un screenshot AVANT de lancer ce script.\n"
            "    Sur Linux, vérifie que xclip ou xsel est installé."
        )

    # ImageGrab peut parfois retourner une liste de chemins (fichiers copiés)
    if isinstance(img, list):
        raise SystemExit(
            "❌  Le presse-papier contient des fichiers, pas une image bitmap.\n"
            f"    Contenu détecté : {img}"
        )

    return img


def save_image(img, output_path: str) -> None:
    """Sauvegarde l'image PIL en PNG, en créant les dossiers intermédiaires si besoin."""
    parent = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(parent, exist_ok=True)

    # Convertit en RGBA si nécessaire pour garantir la compatibilité PNG
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    img.save(output_path, format="PNG", optimize=True)


def main():
    output_path = get_output_path(sys.argv)

    print("📋  Lecture du presse-papier…")
    img = grab_image_from_clipboard()

    print(f"🖼️   Image détectée  : {img.width} × {img.height} px  (mode {img.mode})")
    print(f"💾  Sauvegarde vers : {os.path.abspath(output_path)}")

    save_image(img, output_path)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"✅  Fait ! Fichier sauvegardé ({size_kb:.1f} Ko)")


if __name__ == "__main__":
    main()