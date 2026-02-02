# infrastructure/migration_service.py
"""
Migration service for systematic MWQ file organization.

Handles:
1. Automatic migration when root folder changes
2. UUID assignment for existing projects
3. Legacy filename migration to UUID-based naming
"""

import threading
from typing import Dict, Callable
from infrastructure.file_manager import FileManager
from infrastructure.database import Database


class MigrationService:
    """Orchestrates systematic migration of MWQ files."""

    def __init__(self, db: Database):
        self.db = db
        self.is_running = False
        self._thread = None

    def migrate_on_root_folder_change(self, old_root: str, new_root: str, 
                                     progress_callback=None,
                                     completion_callback=None):
        """
        Handle migration when root folder is changed.
        
        Steps:
        1. Auto-assign UUIDs to legacy projects
        2. Relocate files to new root folder
        3. Rename to systematic UUID-based names if needed
        """
        self.is_running = True
        
        def run_migration():
            try:
                stats = {
                    "uuid_assigned": 0,
                    "files_relocated": 0,
                    "errors": []
                }
                
                if progress_callback:
                    progress_callback("Assignation des UUIDs aux projets existants...")
                
                # Step 1: Assign UUIDs to projects without them
                uuid_stats = self.db.migrate_legacy_filenames_to_uuid()
                stats["uuid_assigned"] = uuid_stats["migrated"]
                stats["errors"].extend(uuid_stats.get("errors", []))
                
                if progress_callback:
                    progress_callback(f"UUIDs assignés: {stats['uuid_assigned']}")
                
                # Step 2: Relocate files if directories are different
                if old_root and new_root and old_root != new_root:
                    if progress_callback:
                        progress_callback("Relocalisation des fichiers...")
                    relocation_stats = FileManager.relocate_files(
                        old_root, new_root, self.db, progress_callback
                    )
                    stats["files_relocated"] = relocation_stats.get("relocated", 0)
                    stats["errors"].extend(relocation_stats.get("errors", []))
                
                if progress_callback:
                    progress_callback(f"Migration terminée. {stats['files_relocated']} fichiers relocalisés.")
                
                if completion_callback:
                    completion_callback(stats)
            
            except Exception as e:
                if completion_callback:
                    completion_callback({
                        "error": str(e),
                        "uuid_assigned": 0,
                        "files_relocated": 0
                    })
            finally:
                self.is_running = False

        # Run in background thread
        self._thread = threading.Thread(target=run_migration, daemon=True)
        self._thread.start()

    def auto_migrate_legacy_files(self, root_folder: str,
                                 progress_callback=None,
                                 completion_callback=None):
        """
        Scan root folder and migrate all legacy-named files to UUID-based naming.
        """
        self.is_running = True
        
        def run_migration():
            try:
                if progress_callback:
                    progress_callback("Scan du répertoire pour fichiers legacy...")
                
                stats = FileManager.migrate_to_uuid_naming(root_folder, self.db)
                
                if progress_callback:
                    progress_callback(
                        f"Migration terminée: {stats['migrated']} fichiers renommés, "
                        f"{stats['already_uuid']} déjà en UUID"
                    )
                
                if completion_callback:
                    completion_callback(stats)
            
            except Exception as e:
                if completion_callback:
                    completion_callback({
                        "error": str(e),
                        "migrated": 0
                    })
            finally:
                self.is_running = False

        # Run in background thread
        self._thread = threading.Thread(target=run_migration, daemon=True)
        self._thread.start()

    def bulk_assign_uuids(self) -> Dict:
        """Assign UUIDs to all projects that don't have them."""
        return self.db.migrate_legacy_filenames_to_uuid()

    def is_migration_running(self) -> bool:
        """Check if migration is currently running."""
        return self.is_running

    def stop_migration(self):
        """Request stop of running migration."""
        self.is_running = False
