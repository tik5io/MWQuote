import os
import threading
from typing import Callable
from infrastructure.database import Database
from infrastructure.persistence import PersistenceService

class Indexer:
    def __init__(self, database: Database):
        self.database = database
        self.is_indexing = False
        self._stop_event = threading.Event()

    def index_directory(self, root_path: str, progress_callback: Callable[[str], None] = None, completion_callback: Callable[[int], None] = None):
        """Start indexing in a background thread."""
        if self.is_indexing:
            return

        self._stop_event.clear()
        self.is_indexing = True
        
        thread = threading.Thread(
            target=self._index_worker,
            args=(root_path, progress_callback, completion_callback)
        )
        thread.daemon = True
        thread.start()

    def index_file(self, filepath: str):
        """Index or re-index a single project file."""
        if not os.path.exists(filepath):
            return
        
        try:
            # Load project to get metadata
            project = PersistenceService.load_project(filepath)
            
            # Prepare data for DB
            qtys = sorted(project.sale_quantities)
            project_data = {
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
                'date_transmise': project.status_dates.get("Transmise")
            }
            
            self.database.upsert_project(project_data)
            return True
        except Exception as e:
            print(f"Error indexing single file {filepath}: {e}")
            return False

    def stop(self):
        """Stop current indexing process."""
        self._stop_event.set()

    def _index_worker(self, root_path: str, progress_callback, completion_callback):
        count = 0
        error_count = 0
        try:
            print(f"Starting indexer on: {root_path}")
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
                                
                            # Load project to get metadata
                            project = PersistenceService.load_project(filepath)
                            
                            # Prepare data for DB
                            qtys = sorted(project.sale_quantities)
                            project_data = {
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
                                'date_transmise': project.status_dates.get("Transmise")
                            }
                            
                            self.database.upsert_project(project_data)
                            print(f"Successfully indexed: {file}")
                            count += 1
                        except Exception as e:
                            print(f"Error indexing {filepath}: {e}")
                            error_count += 1
                            
        except Exception as e:
            print(f"Indexer critical error: {e}")
        finally:
            self.is_indexing = False
            print(f"Indexing finished. Processed {count} files with {error_count} errors.")
            if completion_callback:
                completion_callback(count)
