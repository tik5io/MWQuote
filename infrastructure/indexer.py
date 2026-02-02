import os
import threading
from typing import Callable, Dict
from infrastructure.database import Database
from infrastructure.persistence import PersistenceService


class Indexer:
    def __init__(self, database: Database):
        self.database = database
        self.is_indexing = False
        self._stop_event = threading.Event()

    def index_directory(self, root_path: str,
                       progress_callback: Callable[[str], None] = None,
                       completion_callback: Callable[[int], None] = None,
                       migrate_to_zip: bool = False):
        """Start indexing in a background thread.

        Args:
            root_path: Directory to scan for .mwq files
            progress_callback: Called with status messages
            completion_callback: Called with count when done
            migrate_to_zip: If True, convert legacy JSON files to ZIP format
        """
        if self.is_indexing:
            return

        self._stop_event.clear()
        self.is_indexing = True

        thread = threading.Thread(
            target=self._index_worker,
            args=(root_path, progress_callback, completion_callback, migrate_to_zip)
        )
        thread.daemon = True
        thread.start()

    def index_file(self, filepath: str, migrate_to_zip: bool = False) -> bool:
        """Index or re-index a single project file.

        Args:
            filepath: Path to the .mwq file
            migrate_to_zip: If True, convert legacy JSON to ZIP format

        Returns:
            True if successful, False otherwise
        """
        if not os.path.exists(filepath):
            self.database.mark_missing(filepath)
            return False

        try:
            # Optionally migrate legacy files
            if migrate_to_zip:
                if PersistenceService.migrate_to_zip(filepath):
                    print(f"Migrated to ZIP format: {filepath}")

            # Load project and compute hash
            project, content_hash = PersistenceService.get_project_metadata(filepath)

            # Prepare data for DB
            project_data = self._build_project_data(project, filepath, content_hash)
            self.database.upsert_project(project_data)
            return True
        except Exception as e:
            print(f"Error indexing single file {filepath}: {e}")
            return False

    def _build_project_data(self, project, filepath: str, content_hash: str) -> Dict:
        """Build the project data dict for database insertion."""
        qtys = sorted(project.sale_quantities)
        return {
            'name': project.name,
            'reference': project.reference,
            'client': project.client,
            'filepath': filepath,
            'drawing_filename': project.drawing_filename,
            'tags': project.tags,
            'status': project.status,
            'min_qty': qtys[0] if qtys else 0,
            'max_qty': qtys[-1] if qtys else 0,
            'date_construction': project.status_dates.get("En construction"),
            'date_finalisee': project.status_dates.get("Finalisée"),
            'date_transmise': project.status_dates.get("Transmise"),
            'content_hash': content_hash,
            'export_history': project.export_history
        }

    def stop(self):
        """Stop current indexing process."""
        self._stop_event.set()

    def reconcile(self, progress_callback: Callable[[str], None] = None) -> Dict:
        """Check all indexed files and update their status.

        - Mark missing files as is_missing=1
        - Files found again are unmarked
        - Returns stats dict

        This does NOT scan for new files, only checks existing DB entries.
        """
        stats = self.database.reconcile_files()
        if progress_callback:
            progress_callback(f"Reconciled: {stats['checked']} checked, "
                            f"{stats['missing']} missing, {stats['found']} found")
        return stats

    def _index_worker(self, root_path: str, progress_callback, completion_callback,
                     migrate_to_zip: bool = False):
        count = 0
        error_count = 0
        migrated_count = 0
        reconnected_count = 0

        try:
            print(f"Starting indexer on: {root_path}")

            # First, mark all known files as potentially missing
            # They will be unmarked as we find them
            self.database.mark_missing_files()

            for root, dirs, files in os.walk(root_path):
                if self._stop_event.is_set():
                    print("Indexing stopped by user.")
                    break

                for file in files:
                    if self._stop_event.is_set():
                        break

                    if file.endswith('.mwq'):
                        filepath = os.path.join(root, file)
                        try:
                            if progress_callback:
                                progress_callback(f"Indexing {file}...")

                            # Optionally migrate legacy files
                            if migrate_to_zip:
                                if PersistenceService.migrate_to_zip(filepath):
                                    migrated_count += 1
                                    print(f"Migrated to ZIP format: {file}")

                            # Load project and compute hash
                            project, content_hash = PersistenceService.get_project_metadata(filepath)

                            # Check if this might be a reconnection
                            existing = self.database.find_by_hash(content_hash)
                            if existing and existing.get('is_missing') and existing['filepath'] != filepath:
                                reconnected_count += 1
                                print(f"Reconnecting: {existing['filepath']} -> {filepath}")

                            # Prepare data for DB
                            project_data = self._build_project_data(project, filepath, content_hash)
                            self.database.upsert_project(project_data)
                            count += 1
                        except Exception as e:
                            print(f"Error indexing {filepath}: {e}")
                            error_count += 1

        except Exception as e:
            print(f"Indexer critical error: {e}")
        finally:
            self.is_indexing = False
            summary = (f"Indexing finished. Processed {count} files, "
                      f"{error_count} errors, {migrated_count} migrated, "
                      f"{reconnected_count} reconnected.")
            print(summary)
            if progress_callback:
                progress_callback(summary)
            if completion_callback:
                completion_callback(count)

    def migrate_all_to_zip(self, root_path: str,
                          progress_callback: Callable[[str], None] = None,
                          completion_callback: Callable[[int], None] = None):
        """Migrate all legacy JSON .mwq files to ZIP format.

        This is a convenience method that calls index_directory with migrate_to_zip=True.
        """
        self.index_directory(root_path, progress_callback, completion_callback,
                            migrate_to_zip=True)
