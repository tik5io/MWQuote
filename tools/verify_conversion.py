#!/usr/bin/env python
# tools/verify_conversion.py
"""Vérifie qu'un .mwq donne les MÊMES prix avant et après conversion.

Référence = le code d'un commit (HEAD par défaut), extrait dans un dossier
temporaire : c'est ce que l'application calculait avant le chantier. Le nouveau
code (cet arbre de travail) charge le même fichier ; toutes les valeurs
(prix par quantité, par opération, coût, coefficients, outillage, chiffrage
série) sont comparées.

Usage : python tools/verify_conversion.py FICHIER.mwq [FICHIER2.mwq …] [--ref COMMIT]
Code retour : 0 = tout identique, 1 = au moins un écart ou fichier illisible.
"""
import argparse
import io
import json
import math
import os
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "tools", "price_fingerprint.py")
REL_TOL = 1e-9
ABS_TOL = 1e-9


def extract_reference(ref: str = "HEAD") -> str:
    """Extrait le code du commit `ref` dans un dossier temporaire (sans toucher à .git)."""
    out = subprocess.run(["git", "archive", "--format=tar", ref], cwd=ROOT,
                         capture_output=True, check=True).stdout
    dest = tempfile.mkdtemp(prefix="mwquote_ref_")
    with tarfile.open(fileobj=io.BytesIO(out)) as tf:
        tf.extractall(dest)
    return dest


def fingerprint(code_root: str, mwq_path: str) -> dict:
    proc = subprocess.run([sys.executable, SCRIPT, code_root, mwq_path],
                          capture_output=True, text=True, encoding="utf-8", timeout=300)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout)
                           else f"code retour {proc.returncode}")
    return json.loads(proc.stdout)


def _close(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return a == b


def _walk(a, b, path, diffs):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                diffs.append(f"{path}/{k} : présent d'un seul côté")
            else:
                _walk(a[k], b[k], f"{path}/{k}", diffs)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path} : {len(a)} éléments avant, {len(b)} après")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, f"{path}[{i}]", diffs)
    elif not _close(a, b):
        diffs.append(f"{path} : {a!r} avant, {b!r} après")


def compare(before: dict, after: dict) -> list:
    """Écarts entre deux empreintes ; liste vide = identiques."""
    diffs = []
    _walk(before["entries"], after["entries"], "", diffs)
    return diffs


def verify_file(reference_root: str, mwq_path: str, code_root: str = ROOT) -> list:
    """Écarts « ancien code » vs « nouveau code » pour un fichier ; [] = identique."""
    try:
        before = fingerprint(reference_root, mwq_path)
    except Exception as exc:
        return [f"référence illisible : {exc}"]
    try:
        after = fingerprint(code_root, mwq_path)
    except Exception as exc:
        return [f"lecture par le nouveau code impossible : {exc}"]
    return compare(before, after)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare les prix avant/après conversion.")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--ref", default="HEAD", help="Commit de référence (défaut : HEAD)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    reference_root = extract_reference(args.ref)
    bad = 0
    for path in args.files:
        diffs = verify_file(reference_root, path)
        if diffs:
            bad += 1
            print(f"ÉCART  {os.path.basename(path)}")
            for d in diffs[:15]:
                print(f"         {d}")
        else:
            print(f"OK     {os.path.basename(path)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
