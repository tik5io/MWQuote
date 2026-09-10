# infrastructure/project_folder_service.py
"""
Service de gestion du dossier physique d'un projet série.

Arborescence cible (sur le réseau) :

    <racine>\\<NOM DU CLIENT>\\<NOM DU PROJET>\\...

L'arborescence d'un projet suit celle du dossier modèle :

    <racine>\\0 - EMPTY PROJECT

Emplacements standards à l'intérieur d'un dossier projet :
- Plans client (chiffrage) : TECHNIQUE\\PLAN CLIENT\\CHIFFRAGE
- Devis XLSX (commercial)  : COMMERCIAL
"""

import os
import base64
import shutil
from typing import Callable, Optional, Dict, List

from infrastructure.configuration import ConfigurationService

# Sous-chemins standards (relatifs au dossier projet), calqués sur le dossier modèle.
PLANS_SUBPATH = os.path.join("TECHNIQUE", "PLAN CLIENT", "CHIFFRAGE")
COMMERCIAL_SUBPATH = "COMMERCIAL"
# Devis fournisseur : COMMERCIAL\DEVIS
SUPPLIER_QUOTES_SUBPATH = os.path.join("COMMERCIAL", "DEVIS")
# Documents process (export Fabrication/Qualité) : PROCESS
PROCESS_SUBPATH = "PROCESS"

# Caractères interdits dans un nom de dossier Windows.
_INVALID_CHARS = '<>:"/\\|?*'


def sanitize_folder_name(name: str) -> str:
    """Nettoie un composant de nom de dossier (client ou projet)."""
    if not name:
        return ""
    cleaned = "".join(c for c in name if c not in _INVALID_CHARS)
    # Windows n'autorise pas les espaces / points en fin de nom de dossier.
    return cleaned.strip().rstrip(". ")


class ProjectFolderService:
    """Suggestions de chemin et création d'arborescence pour les projets série."""

    def __init__(self, config: Optional[ConfigurationService] = None):
        self.config = config or ConfigurationService.get_instance()

    # ------------------------------------------------------------------ #
    # Chemins                                                              #
    # ------------------------------------------------------------------ #

    def get_root(self) -> str:
        return self.config.get_series_root_folder()

    def get_template_folder(self) -> str:
        """Dossier modèle dont l'arborescence est copiée (<racine>\\0 - EMPTY PROJECT)."""
        return os.path.join(self.get_root(), self.config.get_empty_project_name())

    def suggest_folder(self, client: str, project_name: str) -> str:
        """Propose un chemin <racine>\\<client>\\<projet> (proposé, mais facultatif).

        Retourne "" si ni le client ni le nom de projet ne sont renseignés.
        """
        root = self.get_root()
        client_dir = sanitize_folder_name(client)
        project_dir = sanitize_folder_name(project_name)
        if not client_dir and not project_dir:
            return ""
        parts = [root]
        if client_dir:
            parts.append(client_dir)
        if project_dir:
            parts.append(project_dir)
        return os.path.join(*parts)

    @staticmethod
    def folder_exists(folder: str) -> bool:
        return bool(folder) and os.path.isdir(folder)

    @staticmethod
    def plans_dir(project_folder: str) -> str:
        return os.path.join(project_folder, PLANS_SUBPATH)

    @staticmethod
    def commercial_dir(project_folder: str) -> str:
        return os.path.join(project_folder, COMMERCIAL_SUBPATH)

    @staticmethod
    def supplier_quotes_dir(project_folder: str) -> str:
        return os.path.join(project_folder, SUPPLIER_QUOTES_SUBPATH)

    @staticmethod
    def process_dir(project_folder: str) -> str:
        return os.path.join(project_folder, PROCESS_SUBPATH)

    def template_available(self) -> bool:
        return os.path.isdir(self.get_template_folder())

    # ------------------------------------------------------------------ #
    # Création d'arborescence                                             #
    # ------------------------------------------------------------------ #

    def create_folder_tree(
        self,
        dest_folder: str,
        overwrite_decider: Optional[Callable[[str], bool]] = None,
    ) -> Dict:
        """Crée `dest_folder` en copiant l'arborescence du dossier modèle.

        - Les dossiers manquants sont créés.
        - Pour chaque fichier du modèle déjà présent à destination, `overwrite_decider`
          (appelé avec le chemin relatif) décide de l'écrasement. Si absent → on
          n'écrase pas.
        - Si le dossier modèle est introuvable, on crée au minimum l'arborescence
          standard (plans + commercial) pour rester exploitable.

        Retourne un dict de statistiques.
        """
        stats = {"created_dirs": 0, "copied_files": 0, "skipped_files": 0, "errors": []}

        os.makedirs(dest_folder, exist_ok=True)

        template = self.get_template_folder()
        if os.path.isdir(template):
            for root, dirs, files in os.walk(template):
                rel = os.path.relpath(root, template)
                target_dir = dest_folder if rel == "." else os.path.join(dest_folder, rel)
                try:
                    if not os.path.isdir(target_dir):
                        os.makedirs(target_dir, exist_ok=True)
                        stats["created_dirs"] += 1
                except Exception as e:
                    stats["errors"].append(f"{target_dir}: {e}")
                    continue

                for fname in files:
                    src = os.path.join(root, fname)
                    dst = os.path.join(target_dir, fname)
                    rel_file = os.path.relpath(dst, dest_folder)
                    try:
                        if os.path.exists(dst):
                            if overwrite_decider is None or not overwrite_decider(rel_file):
                                stats["skipped_files"] += 1
                                continue
                        shutil.copy2(src, dst)
                        stats["copied_files"] += 1
                    except Exception as e:
                        stats["errors"].append(f"{rel_file}: {e}")
        else:
            # Pas de modèle : au minimum l'arborescence standard.
            for sub in (PLANS_SUBPATH, COMMERCIAL_SUBPATH):
                try:
                    os.makedirs(os.path.join(dest_folder, sub), exist_ok=True)
                    stats["created_dirs"] += 1
                except Exception as e:
                    stats["errors"].append(f"{sub}: {e}")

        return stats

    # ------------------------------------------------------------------ #
    # Pré-copie des infos du projet                                       #
    # ------------------------------------------------------------------ #

    def copy_project_plans(
        self,
        project,
        project_folder: str,
        overwrite_decider: Optional[Callable[[str], bool]] = None,
    ) -> Dict:
        """Écrit les plans (documents) du projet dans TECHNIQUE\\PLAN CLIENT\\CHIFFRAGE.

        Les documents sont stockés en base64 dans le .mwq ; on les matérialise sur disque.
        """
        stats = {"copied_files": 0, "skipped_files": 0, "errors": []}
        target = self.plans_dir(project_folder)
        try:
            os.makedirs(target, exist_ok=True)
        except Exception as e:
            stats["errors"].append(f"{target}: {e}")
            return stats

        documents = getattr(project, "documents", None) or []
        for doc in documents:
            filename = getattr(doc, "filename", None)
            data = getattr(doc, "data", None)
            if not filename or not data:
                continue
            # Nom lisible : on retire un éventuel préfixe UUID_ du nom de fichier stocké.
            clean_name = _strip_uuid_prefix(os.path.basename(filename))
            dst = os.path.join(target, clean_name)
            try:
                if os.path.exists(dst):
                    if overwrite_decider is None or not overwrite_decider(clean_name):
                        stats["skipped_files"] += 1
                        continue
                with open(dst, "wb") as f:
                    f.write(base64.b64decode(data))
                stats["copied_files"] += 1
            except Exception as e:
                stats["errors"].append(f"{clean_name}: {e}")
        return stats

    def copy_latest_devis_xlsx(
        self,
        project,
        project_folder: str,
        overwrite_decider: Optional[Callable[[str], bool]] = None,
    ) -> Dict:
        """Écrit le dernier devis XLSX (historique des exports) dans COMMERCIAL.

        Prend l'entrée la plus récente de `export_history` disposant d'un binaire XLSX.
        """
        stats = {"copied_files": 0, "skipped_files": 0, "errors": []}
        target = self.commercial_dir(project_folder)

        history = getattr(project, "export_history", None) or []
        entry = next(
            (e for e in reversed(history) if e.get("xlsx_data_b64")), None
        )
        if entry is None:
            return stats

        filename = entry.get("xlsx_filename") or f"{entry.get('devis_ref', 'devis')}.xlsx"
        filename = os.path.basename(filename)
        try:
            os.makedirs(target, exist_ok=True)
            dst = os.path.join(target, filename)
            if os.path.exists(dst) and (overwrite_decider is None or not overwrite_decider(filename)):
                stats["skipped_files"] += 1
                return stats
            with open(dst, "wb") as f:
                f.write(base64.b64decode(entry["xlsx_data_b64"]))
            stats["copied_files"] += 1
        except Exception as e:
            stats["errors"].append(f"{filename}: {e}")
        return stats

    def copy_supplier_quotes(
        self,
        project,
        project_folder: str,
        overwrite_decider: Optional[Callable[[str], bool]] = None,
    ) -> Dict:
        """Écrit les devis fournisseur (documents des coûts) dans COMMERCIAL\\DEVIS.

        Parcourt les coûts de la version courante ; chaque document attaché à un
        CostItem est matérialisé sur disque (préfixe UUID retiré du nom).
        """
        stats = {"copied_files": 0, "skipped_files": 0, "errors": []}
        target = self.supplier_quotes_dir(project_folder)

        operations = getattr(project, "operations", None) or []
        # Rien à faire si aucun document de coût
        has_docs = any(
            getattr(doc, "filename", None) and getattr(doc, "data", None)
            for op in operations
            for cost in getattr(op, "costs", {}).values()
            for doc in (getattr(cost, "documents", None) or [])
        )
        if not has_docs:
            return stats

        try:
            os.makedirs(target, exist_ok=True)
        except Exception as e:
            stats["errors"].append(f"{target}: {e}")
            return stats

        used_names = set()
        for op in operations:
            for cost in getattr(op, "costs", {}).values():
                for doc in (getattr(cost, "documents", None) or []):
                    filename = getattr(doc, "filename", None)
                    data = getattr(doc, "data", None)
                    if not filename or not data:
                        continue
                    clean_name = _strip_uuid_prefix(os.path.basename(filename))
                    clean_name = _dedupe_name(clean_name, used_names)
                    dst = os.path.join(target, clean_name)
                    try:
                        if os.path.exists(dst) and (
                            overwrite_decider is None or not overwrite_decider(clean_name)
                        ):
                            stats["skipped_files"] += 1
                            continue
                        with open(dst, "wb") as f:
                            f.write(base64.b64decode(data))
                        stats["copied_files"] += 1
                    except Exception as e:
                        stats["errors"].append(f"{clean_name}: {e}")
        return stats


def _dedupe_name(name: str, used: set) -> str:
    """Garantit un nom unique dans un même lot de copie (ajoute _2, _3, …)."""
    if name not in used:
        used.add(name)
        return name
    base, ext = os.path.splitext(name)
    counter = 2
    candidate = f"{base}_{counter}{ext}"
    while candidate in used:
        counter += 1
        candidate = f"{base}_{counter}{ext}"
    used.add(candidate)
    return candidate


def _strip_uuid_prefix(name: str) -> str:
    """Retire un préfixe '<uuid>_' du nom de fichier s'il est présent."""
    import uuid as _uuid
    if len(name) > 37 and name[36] == "_":
        try:
            _uuid.UUID(name[:36])
            return name[37:]
        except (ValueError, AttributeError):
            pass
    return name
