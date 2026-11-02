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

from __future__ import annotations

import os
import base64
import shutil
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, List

from infrastructure.configuration import ConfigurationService
from infrastructure.logging_service import get_module_logger

logger = get_module_logger("ProjectFolderService", "export_project.log")

# Taille des blocs pour la copie en flux des gros fichiers (évite de charger
# ~100 Mo en mémoire et de bloquer l'UI sur un fichier corrompu/lent).
_COPY_CHUNK = 1024 * 1024  # 1 Mio

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

    @staticmethod
    def fabrication_filename(project) -> str:
        """Nom de fichier du document Fabrication/Qualité (même règle que l'UI)."""
        ref = (
            getattr(project, "reference", None)
            or getattr(project, "name", None)
            or "Projet"
        ).strip()
        safe_ref = "".join(
            c if c.isalnum() or c in " -_" else "_" for c in ref
        ).strip() or "Projet"
        return f"{safe_ref}_Fabrication_Qualite.xlsx"

    def fabrication_export_path(self, project, project_folder: str) -> str:
        """Chemin cible du XLSX Fabrication/Qualité dans PROCESS."""
        return os.path.join(self.process_dir(project_folder), self.fabrication_filename(project))

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
                        copy_file_streaming(src, dst)
                        stats["copied_files"] += 1
                    except Exception as e:
                        logger.warning(f"Copie échouée {rel_file} : {e}")
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
                    if overwrite_decider is None or not overwrite_decider(
                        os.path.relpath(dst, project_folder)
                    ):
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
            if os.path.exists(dst) and (
                overwrite_decider is None
                or not overwrite_decider(os.path.relpath(dst, project_folder))
            ):
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
                            overwrite_decider is None
                            or not overwrite_decider(os.path.relpath(dst, project_folder))
                        ):
                            stats["skipped_files"] += 1
                            continue
                        with open(dst, "wb") as f:
                            f.write(base64.b64decode(data))
                        stats["copied_files"] += 1
                    except Exception as e:
                        stats["errors"].append(f"{clean_name}: {e}")
        return stats

    # ------------------------------------------------------------------ #
    # Pré-scan des écrasements                                            #
    # ------------------------------------------------------------------ #

    def scan_overwrite_candidates(self, project, dest_folder: str) -> List[str]:
        """Liste triée des chemins (relatifs à `dest_folder`) des fichiers déjà
        présents qui seraient écrasés par une création/copie complète du dossier.

        Ne modifie rien sur le disque : sert à documenter la validation avant
        écrasement. Les chemins retournés correspondent exactement aux clés
        passées à `overwrite_decider` par les méthodes de copie.
        """
        candidates: List[str] = []

        def _rel(dst: str) -> str:
            return os.path.relpath(dst, dest_folder)

        # 1) Arborescence du dossier modèle.
        template = self.get_template_folder()
        if os.path.isdir(template):
            for root, _dirs, files in os.walk(template):
                rel = os.path.relpath(root, template)
                target_dir = dest_folder if rel == "." else os.path.join(dest_folder, rel)
                for fname in files:
                    dst = os.path.join(target_dir, fname)
                    if os.path.exists(dst):
                        candidates.append(_rel(dst))

        # 2) Plans du projet → TECHNIQUE\PLAN CLIENT\CHIFFRAGE
        plans_target = self.plans_dir(dest_folder)
        for doc in (getattr(project, "documents", None) or []):
            filename = getattr(doc, "filename", None)
            data = getattr(doc, "data", None)
            if not filename or not data:
                continue
            clean_name = _strip_uuid_prefix(os.path.basename(filename))
            dst = os.path.join(plans_target, clean_name)
            if os.path.exists(dst):
                candidates.append(_rel(dst))

        # 3) Dernier devis XLSX → COMMERCIAL
        history = getattr(project, "export_history", None) or []
        entry = next((e for e in reversed(history) if e.get("xlsx_data_b64")), None)
        if entry is not None:
            filename = entry.get("xlsx_filename") or f"{entry.get('devis_ref', 'devis')}.xlsx"
            dst = os.path.join(self.commercial_dir(dest_folder), os.path.basename(filename))
            if os.path.exists(dst):
                candidates.append(_rel(dst))

        # 4) Devis fournisseur → COMMERCIAL\DEVIS (même dédoublonnage que la copie)
        quotes_target = self.supplier_quotes_dir(dest_folder)
        used_names: set = set()
        for op in (getattr(project, "operations", None) or []):
            for cost in getattr(op, "costs", {}).values():
                for doc in (getattr(cost, "documents", None) or []):
                    filename = getattr(doc, "filename", None)
                    data = getattr(doc, "data", None)
                    if not filename or not data:
                        continue
                    clean_name = _strip_uuid_prefix(os.path.basename(filename))
                    clean_name = _dedupe_name(clean_name, used_names)
                    dst = os.path.join(quotes_target, clean_name)
                    if os.path.exists(dst):
                        candidates.append(_rel(dst))

        # 5) Export Fabrication/Qualité → PROCESS (toujours régénéré à la création).
        fab_dst = self.fabrication_export_path(project, dest_folder)
        if os.path.exists(fab_dst):
            candidates.append(_rel(fab_dst))

        # Dédoublonnage en conservant un ordre déterministe.
        return sorted(set(candidates))

    # ------------------------------------------------------------------ #
    # Disponibilité du réseau                                             #
    # ------------------------------------------------------------------ #

    def root_available(self) -> bool:
        """Le dossier racine réseau est-il accessible ?

        Un accès réseau indisponible/lent fait lever/traîner `os.path.isdir` ;
        on isole l'appel pour renvoyer un simple booléen sans planter l'UI.
        """
        root = self.get_root()
        try:
            return bool(root) and os.path.isdir(root)
        except OSError as e:
            logger.warning(f"Racine réseau inaccessible ({root}) : {e}")
            return False

    # ------------------------------------------------------------------ #
    # Plan d'export par version                                           #
    # ------------------------------------------------------------------ #

    def build_export_items(self, project) -> List[ExportItem]:
        """Liste des éléments exportables du projet, un sous-dossier par version.

        - Plans de la pièce (par version)       → TECHNIQUE\\PLAN CLIENT\\CHIFFRAGE\\V{n}
        - Offres client XLSX (par version)      → COMMERCIAL\\V{n}
        - Devis fournisseur (par version)       → COMMERCIAL\\DEVIS\\V{n}
        - Fabrication / Qualité (par version)   → PROCESS\\V{n} (généré à la volée)

        Les noms de fichiers sont nettoyés (préfixe UUID retiré) et dédoublonnés
        par dossier cible.
        """
        items: List[ExportItem] = []

        for version in getattr(project, "versions", None) or []:
            vidx = getattr(version, "version_index", 1)
            tag = version_tag(vidx)

            # 1) Plans de la pièce (documents de la version).
            plans_dir = os.path.join(CATEGORY_BASE_SUBPATH[CATEGORY_PLAN], tag)
            used = set()
            for doc in (getattr(version, "documents", None) or []):
                filename = getattr(doc, "filename", None)
                data = getattr(doc, "data", None)
                if not filename or not data:
                    continue
                name = _dedupe_name(_strip_uuid_prefix(os.path.basename(filename)), used)
                items.append(ExportItem(CATEGORY_PLAN, vidx, plans_dir, name, data_b64=data))

            # 2) Devis fournisseur (documents attachés aux coûts de la version).
            sup_dir = os.path.join(CATEGORY_BASE_SUBPATH[CATEGORY_SUPPLIER], tag)
            used = set()
            for op in (getattr(version, "operations", None) or []):
                for cost in getattr(op, "costs", {}).values():
                    for doc in (getattr(cost, "documents", None) or []):
                        filename = getattr(doc, "filename", None)
                        data = getattr(doc, "data", None)
                        if not filename or not data:
                            continue
                        name = _dedupe_name(_strip_uuid_prefix(os.path.basename(filename)), used)
                        items.append(ExportItem(CATEGORY_SUPPLIER, vidx, sup_dir, name, data_b64=data))

            # 4) Fabrication / Qualité : un document généré par version.
            fab_dir = os.path.join(CATEGORY_BASE_SUBPATH[CATEGORY_FABRICATION], tag)
            items.append(ExportItem(
                CATEGORY_FABRICATION, vidx, fab_dir,
                self.fabrication_filename(project), generate_fabrication=True,
            ))

        # 3) Offres client XLSX : depuis l'historique (chaque indice embarque son XLSX).
        history = getattr(project, "export_history", None) or []
        used_by_dir: Dict[str, set] = {}
        for entry in history:
            if not entry.get("xlsx_data_b64"):
                continue
            vidx = entry.get("version_index", 1)
            tag = version_tag(vidx)
            off_dir = os.path.join(CATEGORY_BASE_SUBPATH[CATEGORY_OFFER], tag)
            raw = entry.get("xlsx_filename") or f"{entry.get('devis_ref', 'offre')}.xlsx"
            used = used_by_dir.setdefault(off_dir, set())
            name = _dedupe_name(os.path.basename(raw), used)
            items.append(ExportItem(
                CATEGORY_OFFER, vidx, off_dir, name, data_b64=entry["xlsx_data_b64"],
            ))

        return items

    def run_export(
        self,
        project,
        dest_folder: str,
        items: List[ExportItem],
        create_dirs: Optional[List[str]] = None,
        model_files: Optional[List[str]] = None,
        overwrite_decider: Optional[Callable[[str], bool]] = None,
    ) -> Dict:
        """Exécute l'export des `items` sélectionnés dans `dest_folder`.

        - `create_dirs` : dossiers relatifs à créer (vides), p. ex. ceux cochés
          dans l'arborescence modèle.
        - `model_files` : chemins (relatifs au dossier modèle) de fichiers du
          modèle à copier à l'identique sous `dest_folder` (copie en flux,
          robuste aux gros fichiers).
        - `overwrite_decider` : appelé avec le chemin relatif d'un fichier déjà
          présent ; renvoie True pour écraser. Absent → on n'écrase pas.

        Robuste : chaque élément est traité dans son propre try/except ; un échec
        n'interrompt pas les suivants. Retourne un rapport détaillé.
        """
        report = {
            "created_dirs": 0,
            "copied_files": 0,
            "skipped_files": 0,
            "errors": [],              # [(rel_path, message)]
            "copied": [],              # [rel_path]
        }

        try:
            os.makedirs(dest_folder, exist_ok=True)
        except Exception as e:
            report["errors"].append((dest_folder, str(e)))
            return report

        for rel in (create_dirs or []):
            try:
                os.makedirs(os.path.join(dest_folder, rel), exist_ok=True)
                report["created_dirs"] += 1
            except Exception as e:
                logger.warning(f"Création dossier échouée {rel} : {e}")
                report["errors"].append((rel, str(e)))

        # Fichiers du dossier modèle (p. ex. gabarits lourds ~100 Mo) en flux.
        template = self.get_template_folder()
        for rel in (model_files or []):
            dst = os.path.join(dest_folder, rel)
            try:
                if os.path.exists(dst) and (
                    overwrite_decider is None or not overwrite_decider(rel)
                ):
                    report["skipped_files"] += 1
                    continue
                copy_file_streaming(os.path.join(template, rel), dst)
                report["copied_files"] += 1
                report["copied"].append(rel)
            except Exception as e:
                logger.warning(f"Copie modèle échouée {rel} : {e}")
                report["errors"].append((rel, str(e)))

        # Pré-générer les Fabrication/Qualité par version (une seule bascule de version).
        fab_cache: Dict[int, Optional[bytes]] = {}
        if any(it.generate_fabrication for it in items):
            fab_cache = self._generate_fabrication_by_version(
                project, sorted({it.version_index for it in items if it.generate_fabrication})
            )

        for item in items:
            rel = item.rel_path
            dst = os.path.join(dest_folder, rel)
            try:
                if os.path.exists(dst) and (
                    overwrite_decider is None or not overwrite_decider(rel)
                ):
                    report["skipped_files"] += 1
                    continue

                if item.generate_fabrication:
                    data = fab_cache.get(item.version_index)
                    if data is None:
                        raise RuntimeError("génération Fabrication/Qualité indisponible")
                    write_bytes_streaming(data, dst)
                else:
                    write_bytes_streaming(base64.b64decode(item.data_b64 or ""), dst)

                report["copied_files"] += 1
                report["copied"].append(rel)
            except Exception as e:
                logger.warning(f"Export échoué {rel} : {e}")
                report["errors"].append((rel, str(e)))

        return report

    def _generate_fabrication_by_version(self, project, version_indices) -> Dict[int, Optional[bytes]]:
        """Génère le XLSX Fabrication/Qualité pour chaque version (en mémoire).

        Bascule temporairement la version courante du projet, génère, puis
        restaure. Un échec sur une version renvoie None pour cette version.
        """
        import io
        from infrastructure.export_service import ExportService

        result: Dict[int, Optional[bytes]] = {}
        exporter = ExportService()
        original = getattr(project, "current_version_index", None)
        try:
            for vidx in version_indices:
                try:
                    if hasattr(project, "switch_to_version"):
                        project.switch_to_version(vidx)
                    buffer = io.BytesIO()
                    exporter.export_fabrication_quality(project, buffer)
                    result[vidx] = buffer.getvalue()
                except Exception as e:
                    logger.warning(f"Fabrication/Qualité V{vidx} échouée : {e}")
                    result[vidx] = None
        finally:
            if original is not None and hasattr(project, "switch_to_version"):
                try:
                    project.switch_to_version(original)
                except Exception:
                    pass
        return result


def copy_file_streaming(src: str, dst: str, chunk: int = _COPY_CHUNK) -> None:
    """Copie `src` vers `dst` en flux (par blocs), puis recopie les métadonnées.

    Robuste pour les gros fichiers (~100 Mo) : rien n'est chargé entièrement en
    mémoire. Le fichier destination est écrit sous un nom temporaire puis
    renommé, afin de ne pas laisser de fichier tronqué si la copie échoue en
    cours de route (réseau lent/coupé).
    """
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    tmp = dst + ".part"
    try:
        with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst, length=chunk)
        os.replace(tmp, dst)
        try:
            shutil.copystat(src, dst)
        except Exception:
            # Les dates/permissions ne sont pas critiques : on ne fait pas échouer.
            pass
    except Exception:
        # Nettoyer le fichier partiel pour ne pas laisser de copie tronquée.
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def write_bytes_streaming(data: bytes, dst: str, chunk: int = _COPY_CHUNK) -> None:
    """Écrit `data` vers `dst` par blocs, via un fichier temporaire (atomique)."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    tmp = dst + ".part"
    try:
        with open(tmp, "wb") as fdst:
            for off in range(0, len(data), chunk):
                fdst.write(data[off:off + chunk])
        os.replace(tmp, dst)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def version_tag(version_index: int) -> str:
    """Nom du sous-dossier par version (V1, V2…)."""
    return f"V{int(version_index)}"


# Catégories d'éléments exportables.
CATEGORY_PLAN = "plan"
CATEGORY_OFFER = "offre"
CATEGORY_SUPPLIER = "devis_fournisseur"
CATEGORY_FABRICATION = "fabrication"

CATEGORY_LABELS = {
    CATEGORY_PLAN: "Plans de la pièce",
    CATEGORY_OFFER: "Offre client (XLSX)",
    CATEGORY_SUPPLIER: "Devis fournisseur",
    CATEGORY_FABRICATION: "Fabrication / Qualité",
}

# Sous-dossier cible (sans le tag de version) par catégorie.
CATEGORY_BASE_SUBPATH = {
    CATEGORY_PLAN: PLANS_SUBPATH,
    CATEGORY_OFFER: COMMERCIAL_SUBPATH,
    CATEGORY_SUPPLIER: SUPPLIER_QUOTES_SUBPATH,
    CATEGORY_FABRICATION: PROCESS_SUBPATH,
}


@dataclass
class ExportItem:
    """Un élément exportable du projet, rattaché à une version et à un dossier cible.

    - `rel_dir` : dossier cible relatif au dossier projet (inclut le tag de version),
      p. ex. ``COMMERCIAL\\V1``.
    - `data_b64` : contenu stocké (plan, devis, offre XLSX) à matérialiser.
    - `generate_fabrication` : l'élément est généré à la volée depuis la version.
    """

    category: str
    version_index: int
    rel_dir: str
    filename: str
    data_b64: Optional[str] = None
    generate_fabrication: bool = False

    @property
    def rel_path(self) -> str:
        return os.path.join(self.rel_dir, self.filename)


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
