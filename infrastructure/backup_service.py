# infrastructure/backup_service.py
"""Sauvegarde automatique hebdomadaire : base d'index + fichiers projets (.mwq).

Une sauvegarde est un zip `mwquote-backup-YYYYMMDD-HHMMSS.zip` contenant :
  - `mwquote_index.db`            copie cohérente de la base (API de sauvegarde SQLite),
                                  compteurs de numéros d'offre compris (non reconstructibles) ;
  - `<dossier projets>/…`         tous les .mwq (même disposition que
                                  `Database.backup_database_with_projects`, donc restaurable
                                  par `Database.restore_database`) ;
  - `_MWQuote_config/app_config.json`  clients, tags, dossiers racine.

Au démarrage, `start_background()` crée une sauvegarde si la dernière date de plus de
7 jours, dans un thread (l'interface n'est jamais bloquée), puis ne garde que les N plus
récentes. Une erreur est journalisée, jamais remontée à l'utilisateur.
"""
import datetime
import json
import logging
import os
import sqlite3
import tempfile
import threading
import zipfile
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "mwquote-backup-"
BACKUP_SUFFIX = ".zip"
CONFIG_ARCDIR = "_MWQuote_config"
DB_ARCNAME = "mwquote_index.db"
DEFAULT_INTERVAL_DAYS = 7
DEFAULT_KEEP = 8


class BackupService:
    def __init__(self, db_path: str, projects_root: str, config_path: str, backup_dir: str,
                 keep: int = DEFAULT_KEEP, interval_days: int = DEFAULT_INTERVAL_DAYS):
        self.db_path = db_path
        self.projects_root = projects_root
        self.config_path = config_path
        self.backup_dir = backup_dir
        self.keep = max(1, keep)
        self.interval = datetime.timedelta(days=interval_days)

    # ------------------------------------------------------------------ état

    @staticmethod
    def _parse_stamp(filename: str) -> Optional[datetime.datetime]:
        if not (filename.startswith(BACKUP_PREFIX) and filename.endswith(BACKUP_SUFFIX)):
            return None
        stamp = filename[len(BACKUP_PREFIX):-len(BACKUP_SUFFIX)]
        try:
            return datetime.datetime.strptime(stamp, "%Y%m%d-%H%M%S")
        except ValueError:
            return None

    def list_backups(self) -> List[Tuple[datetime.datetime, str]]:
        """[(date, chemin)] des sauvegardes, de la plus ancienne à la plus récente."""
        if not os.path.isdir(self.backup_dir):
            return []
        found = []
        for name in os.listdir(self.backup_dir):
            stamp = self._parse_stamp(name)
            if stamp:
                found.append((stamp, os.path.join(self.backup_dir, name)))
        return sorted(found)

    def last_backup(self) -> Optional[datetime.datetime]:
        backups = self.list_backups()
        return backups[-1][0] if backups else None

    def is_due(self, now: datetime.datetime = None) -> bool:
        now = now or datetime.datetime.now()
        last = self.last_backup()
        return last is None or now - last >= self.interval

    # ------------------------------------------------------------ sauvegarde

    def create_backup(self, now: datetime.datetime = None) -> str:
        """Écrit une sauvegarde complète et retourne son chemin (écriture atomique)."""
        now = now or datetime.datetime.now()
        os.makedirs(self.backup_dir, exist_ok=True)
        final_path = os.path.join(self.backup_dir, f"{BACKUP_PREFIX}{now:%Y%m%d-%H%M%S}{BACKUP_SUFFIX}")
        tmp_zip = final_path + ".part"
        tmp_db = None
        try:
            tmp_db = self._snapshot_database()
            n_projects = 0
            # .mwq déjà compressés : ZIP_STORED évite de recompresser ~100 Mo pour rien
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
                if tmp_db:
                    zf.write(tmp_db, arcname=DB_ARCNAME)
                if self.config_path and os.path.isfile(self.config_path):
                    zf.write(self.config_path, arcname=f"{CONFIG_ARCDIR}/{os.path.basename(self.config_path)}")
                if self.projects_root and os.path.isdir(self.projects_root):
                    folder_name = os.path.basename(os.path.normpath(self.projects_root))
                    for root, _dirs, files in os.walk(self.projects_root):
                        for name in files:
                            if not name.lower().endswith(".mwq"):
                                continue
                            full = os.path.join(root, name)
                            zf.write(full, arcname=os.path.join(
                                folder_name, os.path.relpath(full, self.projects_root)))
                            n_projects += 1
                zf.writestr("MANIFEST.json", json.dumps(
                    {"created": now.isoformat(timespec="seconds"), "projects": n_projects,
                     "projects_root": self.projects_root}, ensure_ascii=False, indent=2))
            os.replace(tmp_zip, final_path)
            logger.info("Sauvegarde créée : %s (%d projets)", final_path, n_projects)
            return final_path
        except Exception:
            if os.path.exists(tmp_zip):
                try:
                    os.remove(tmp_zip)
                except OSError:
                    pass
            raise
        finally:
            if tmp_db and os.path.exists(tmp_db):
                try:
                    os.remove(tmp_db)
                except OSError:
                    pass

    def _snapshot_database(self) -> Optional[str]:
        """Copie cohérente de la base (même si l'application l'utilise)."""
        if not self.db_path or not os.path.isfile(self.db_path):
            return None
        fd, tmp_path = tempfile.mkstemp(prefix="mwquote_db_", suffix=".db")
        os.close(fd)
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return tmp_path

    def prune(self) -> List[str]:
        """Supprime les sauvegardes au-delà des `keep` plus récentes ; retourne celles retirées."""
        backups = self.list_backups()
        removed = []
        for _stamp, path in backups[:-self.keep] if len(backups) > self.keep else []:
            try:
                os.remove(path)
                removed.append(path)
            except OSError:
                logger.warning("Impossible de supprimer l'ancienne sauvegarde %s", path)
        return removed

    def run_if_due(self, now: datetime.datetime = None) -> Optional[str]:
        """Sauvegarde si la dernière a plus d'une semaine, puis fait le ménage. None si rien à faire."""
        if not self.is_due(now):
            return None
        path = self.create_backup(now)
        self.prune()
        return path

    def start_background(self, on_done: Callable[[Optional[str], Optional[Exception]], None] = None
                         ) -> threading.Thread:
        """Lance `run_if_due` dans un thread daemon ; `on_done(chemin|None, erreur|None)` à la fin."""
        def _work():
            try:
                path = self.run_if_due()
                error = None
            except Exception as exc:   # jamais de crash au démarrage à cause d'un backup
                logger.exception("Sauvegarde automatique échouée")
                path, error = None, exc
            if on_done:
                try:
                    on_done(path, error)
                except Exception:
                    logger.exception("Rappel de sauvegarde en échec")

        thread = threading.Thread(target=_work, name="mwquote-backup", daemon=True)
        thread.start()
        return thread
