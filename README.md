# MWQuote

Application desktop Python (`wxPython`) pour créer, éditer, analyser et comparer des devis techniques.

## Fonctionnalités

- Recherche et analyse de projets `.mwq`
- Éditeur de quote (opérations, coûts, quantités, statuts, tags)
- Export Excel (`.xlsx`) via template
- Miniature de preview projet (collage depuis le presse-papiers)
- Build Windows via `PyInstaller`

## Prérequis

- Python 3.11+ (3.12 recommandé)
- Windows (usage principal du projet)

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install wxPython Pillow openpyxl pyinstaller
```

## Lancer l’application

```bash
python MainApp.py
```

## Build exécutable

```bash
python build.py
```

Options utiles :

```bash
python build.py --onefile
python build.py --name MWQuote
```

## Structure rapide

- `MainApp.py` : point d’entrée principal
- `QuoteEditor_app.py` : ouverture/gestion de l’éditeur
- `ui/` : frames, panels et composants UI
- `infrastructure/` : persistance, indexation, export, config, DB
- `domain/` : modèles métier
- `assets/` : templates et ressources


