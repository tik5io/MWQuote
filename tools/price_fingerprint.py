#!/usr/bin/env python
# tools/price_fingerprint.py
"""Empreinte des prix d'un .mwq, calculée avec le code d'un répertoire donné.

Usage : python price_fingerprint.py <racine_du_code> <fichier.mwq>

Le script est volontairement indépendant du modèle : il n'utilise que l'API
commune à l'ancien code (commit de référence) et au nouveau (versions,
total_price, sale_quantities, serie_data), pour que tools/verify_conversion.py
puisse comparer ce que calculait l'application AVANT la conversion avec ce
qu'elle calcule APRÈS. Écrit un JSON sur la sortie standard.
"""
import json
import os
import sys


def _op_digest(project):
    return [[op.label, sorted(op.costs)] for op in project.operations]


def _lot_entry(project, version):
    quantities = sorted(project.sale_quantities)
    rates = project.volume_margin_rates or {}
    prices = {}
    for q in quantities:
        prices[str(q)] = {
            "total": project.total_price(q),
            "ops": [op.total_with_margins(q) for op in project.operations],
            "cost": [op.total_cost(q) for op in project.operations],
        }
    tooling = 0.0
    for op in project.operations:
        for cost in op.costs.values():
            if cost.cost_type.name == "TOOLING" and cost.pricing:
                tooling += float(cost.pricing.fixed_price or 0.0)
    return {
        "rates": {str(q): rates.get(q) for q in quantities},
        "structure": _op_digest(project),
        "tooling": tooling,
        "prices": prices,
    }


def _serie_entry(sd):
    return {
        "annual_volume": sd.annual_volume,
        "selling_price": sd.selling_price_per_piece(),
        "total_cost": sd.total_cost_per_piece(),
        "machine_posts": len(sd.machine_posts),
    }


def fingerprint(root, path):
    sys.path.insert(0, root)
    os.chdir(root)
    from infrastructure.persistence import PersistenceService

    project = PersistenceService.load_project(path)
    entries = {}
    for version in project.versions:
        project.switch_to_version(version.version_index)
        phase = getattr(version, "phase", None)      # nouveau modèle : une phase par version
        is_serie_version = phase is not None and phase.kind.name == "SERIE"
        if is_serie_version:
            origin = version.created_from_version or version.version_index
            entries[f"{origin}:serie"] = _serie_entry(project.serie_data)
            continue
        entries[f"{version.version_index}:lot"] = _lot_entry(project, version)
        if phase is None and getattr(project, "serie_data", None) is not None:
            # Ancien modèle : chiffrage série porté par la même version
            entries[f"{version.version_index}:serie"] = _serie_entry(project.serie_data)
    return {"entries": entries}


if __name__ == "__main__":
    json.dump(fingerprint(sys.argv[1], sys.argv[2]), sys.stdout)
