#!/usr/bin/env python
# tools/convert_base.py
"""Conversion one-shot de toute la base de projets au format courant (3.3).

Garde-fou d'intégrité (les prix de la base sont critiques) — pour CHAQUE .mwq :
  1. les prix calculés par le code de référence (commit HEAD par défaut : ce que
     l'application faisait avant la conversion) sont comparés à ceux du nouveau
     code sur le fichier d'origine. Au moindre écart le fichier n'est PAS écrit ;
  2. l'original est copié dans le dossier de sauvegardes
     (LOCALAPPDATA/MWQuote/backups/format-<ancienne version>/), jamais écrasé ;
  3. le fichier est réécrit, puis RELU : ses prix doivent être identiques à
     ceux d'avant écriture, sinon l'original est restauré depuis la sauvegarde.

Usage :
    python tools/convert_base.py [RACINE] [--dry-run] [--ref COMMIT]

--dry-run exécute la vérification complète (étape 1) sans rien écrire : c'est
la répétition à faire avant la vraie conversion. Sans RACINE, le dossier de
devis configuré est utilisé.
"""
import argparse
import os
import shutil
import sys

# Rendre les paquets domain/ et infrastructure/ importables quel que soit le cwd.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from infrastructure.file_manager import FileManager
from infrastructure.persistence import PersistenceService, MWQ_VERSION
from verify_conversion import extract_reference, fingerprint, compare


def convert_file(path: str, reference_root: str, dry_run: bool = False) -> tuple:
    """Convertit un fichier avec garde-fou. Retourne (statut, détails).

    statuts : « propre » (déjà au format courant), « vérifié » (dry-run, prêt),
    « converti », « bloqué » (écart de prix, fichier non écrit), « erreur ».
    """
    before_version = PersistenceService.read_file_format_version(path)
    if before_version == MWQ_VERSION:
        return "propre", [before_version]

    try:
        reference = fingerprint(reference_root, path)
    except Exception as exc:
        return "bloqué", [f"référence illisible : {exc}"]
    try:
        converted = fingerprint(_ROOT, path)
    except Exception as exc:
        return "bloqué", [f"lecture par le nouveau code impossible : {exc}"]
    diffs = compare(reference, converted)
    if diffs:
        return "bloqué", diffs
    if dry_run:
        return "vérifié", [before_version]

    backup = PersistenceService.backup_before_format_upgrade(path)  # copie d'origine, jamais écrasée
    try:
        project = PersistenceService.load_project(path)
        PersistenceService.save_project(project, path)
        rewritten = fingerprint(_ROOT, path)
        post_diffs = compare(converted, rewritten)
        if PersistenceService.read_file_format_version(path) != MWQ_VERSION:
            post_diffs.append("le fichier réécrit n'est pas au format courant")
    except Exception as exc:
        post_diffs = [f"échec pendant la réécriture : {exc}"]
    if post_diffs:
        if backup and os.path.exists(backup):
            shutil.copy2(backup, path)          # restauration de l'original
            post_diffs.append("original restauré depuis la sauvegarde")
        return "erreur", post_diffs
    return "converti", [before_version]


def convert_base(root_folder: str, dry_run: bool = False, ref: str = "HEAD") -> dict:
    files = FileManager.get_all_mwq_files(root_folder)
    report = {"root": root_folder, "total": len(files), "converti": 0, "vérifié": 0,
              "propre": 0, "bloqué": 0, "erreur": 0, "details": []}
    reference_root = extract_reference(ref)
    try:
        for path in files:
            status, details = convert_file(path, reference_root, dry_run=dry_run)
            report[status] += 1
            report["details"].append((path, status, details))
    finally:
        shutil.rmtree(reference_root, ignore_errors=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Conversion one-shot de la base MWQuote (avec garde-fou d'intégrité).")
    parser.add_argument("root", nargs="?", default=None, help="Dossier racine des .mwq (défaut : dossier configuré)")
    parser.add_argument("--dry-run", action="store_true", help="Vérifier sans rien écrire")
    parser.add_argument("--ref", default="HEAD", help="Commit de référence pour les prix (défaut : HEAD)")
    args = parser.parse_args(argv)

    # Console Windows (cp1252) : éviter un crash d'encodage sur les chemins accentués.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    root = args.root
    if not root:
        from infrastructure.configuration import ConfigurationService
        root = ConfigurationService.get_instance().get_quotes_root_folder()

    if not root or not os.path.isdir(root):
        print(f"Dossier racine introuvable : {root!r}", file=sys.stderr)
        return 2

    print(f"Racine     : {root}")
    print(f"Référence  : {args.ref}")
    print(f"Mode       : {'DRY-RUN (vérification, aucune écriture)' if args.dry_run else 'conversion en place (backup auto)'}")
    report = convert_base(root, dry_run=args.dry_run, ref=args.ref)

    for path, status, details in report["details"]:
        if status in ("bloqué", "erreur"):
            print(f"  [{status.upper()}] {os.path.basename(path)}")
            for d in details[:8]:
                print(f"        {d}")
        elif status != "propre":
            print(f"  [{status}] {os.path.basename(path)}")

    print("-" * 60)
    print(f"Total        : {report['total']}")
    print(f"Déjà propres : {report['propre']}")
    print(f"Vérifiés     : {report['vérifié']}")
    print(f"Convertis    : {report['converti']}")
    print(f"Bloqués      : {report['bloqué']}  (écart de prix : NON écrits)")
    print(f"Erreurs      : {report['erreur']}")
    return 1 if (report["bloqué"] or report["erreur"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
