# infrastructure/file_manager.py
"""
File management service for MWQ files with UUID-based organization.

This service handles:
- UUID generation and management for MWQ files
- Automatic file relocation when root folder changes
- Migration of legacy files with manual naming to UUID-based naming
- Consistent file path generation
"""

import os
import shutil
import uuid
from typing import Optional, Dict, List
from pathlib import Path


class FileManager:
    """Manages MWQ file organization with UUID-based systematic naming."""

    MWQ_EXTENSION = ".mwq"
    
    @staticmethod
    def generate_uuid() -> str:
        """Generate a unique identifier for a new MWQ file."""
        return str(uuid.uuid4())

    @staticmethod
    def get_safe_filename(project_ref: str, project_name: str, max_len: int = 50) -> str:
        """
        Create a safe, human-readable filename component.
        
        Used as suffix after UUID for better readability.
        Removes special characters and limits length.
        """
        # Combine reference and name
        parts = [project_ref, project_name]
        combined = "_".join(p for p in parts if p).strip()
        
        # Remove/replace problematic characters
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in combined)
        safe_name = safe_name.strip("_").lower()
        
        # Limit length
        if len(safe_name) > max_len:
            safe_name = safe_name[:max_len]
        
        return safe_name or "unnamed"

    @staticmethod
    def generate_mwq_filename(project_ref: str = "", project_name: str = "", 
                             use_uuid: bool = True) -> str:
        """
        Generate a systematic MWQ filename.
        
        Format:
        - With UUID: {uuid}_{reference}_{name}.mwq
        - Legacy: Based on parameters without UUID
        
        Example: 550e8400-e29b-41d4-a716-446655440000_QUOTE-001_widget-case.mwq
        """
        if use_uuid:
            file_uuid = FileManager.generate_uuid()
            safe_suffix = FileManager.get_safe_filename(project_ref, project_name)
            
            if safe_suffix and safe_suffix != "unnamed":
                return f"{file_uuid}_{safe_suffix}{FileManager.MWQ_EXTENSION}"
            else:
                return f"{file_uuid}{FileManager.MWQ_EXTENSION}"
        else:
            # Legacy format (for backward compatibility during migration)
            safe_name = FileManager.get_safe_filename(project_ref, project_name)
            return f"{safe_name}{FileManager.MWQ_EXTENSION}"

    @staticmethod
    def extract_uuid_from_filename(filename: str) -> Optional[str]:
        """
        Extract UUID from a systematic MWQ filename.
        
        Returns None if the file is not in UUID format.
        """
        name = Path(filename).stem  # Remove extension
        
        # Try to extract UUID (36 chars: 8-4-4-4-12 format)
        if len(name) >= 36:
            potential_uuid = name[:36]
            if FileManager._is_valid_uuid(potential_uuid):
                return potential_uuid
        
        return None

    @staticmethod
    def _is_valid_uuid(value: str) -> bool:
        """Check if string is a valid UUID."""
        try:
            uuid.UUID(value)
            return True
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def get_mwq_path(root_folder: str, mwq_uuid: str, 
                    project_ref: str = "", project_name: str = "") -> str:
        """
        Get the full path where a MWQ file should be stored.
        
        Always uses systematic naming with UUID.
        """
        if not root_folder:
            raise ValueError("Root folder not configured")
        
        # Create folder if needed
        os.makedirs(root_folder, exist_ok=True)
        
        # Generate systematic filename with UUID
        filename = FileManager.generate_mwq_filename(
            project_ref, project_name, use_uuid=False
        )
        
        # Use UUID as base to ensure uniqueness
        base_name = f"{mwq_uuid}_{filename}" if filename != f"{FileManager.MWQ_EXTENSION}" else f"{mwq_uuid}{FileManager.MWQ_EXTENSION}"
        
        return os.path.join(root_folder, base_name)

    @staticmethod
    def migrate_to_uuid_naming(root_folder: str, db):
        """
        Scan root folder and migrate all legacy-named files to UUID naming.
        
        Returns migration statistics.
        """
        if not os.path.exists(root_folder):
            return {"error": "Root folder does not exist", "migrated": 0}
        
        stats = {
            "scanned": 0,
            "already_uuid": 0,
            "migrated": 0,
            "errors": [],
            "details": []
        }
        
        # Find all .mwq files
        for root, _, files in os.walk(root_folder):
            for filename in files:
                if not filename.lower().endswith(FileManager.MWQ_EXTENSION):
                    continue
                
                stats["scanned"] += 1
                old_path = os.path.join(root, filename)
                
                # Skip if already has UUID format
                if FileManager.extract_uuid_from_filename(filename):
                    stats["already_uuid"] += 1
                    continue
                
                try:
                    # Generate new UUID-based filename
                    new_filename = FileManager.generate_mwq_filename(use_uuid=True)
                    new_path = os.path.join(root_folder, new_filename)
                    
                    # Ensure uniqueness
                    counter = 1
                    base_name, ext = os.path.splitext(new_filename)
                    while os.path.exists(new_path):
                        new_filename = f"{base_name}_{counter}{ext}"
                        new_path = os.path.join(root_folder, new_filename)
                        counter += 1
                    
                    # Rename file (move to root folder with new name)
                    shutil.move(old_path, new_path)
                    
                    # Update database if provided
                    if db:
                        db.update_filepath_by_filepath(old_path, new_path)
                    
                    stats["migrated"] += 1
                    stats["details"].append({
                        "old": old_path,
                        "new": new_path,
                        "status": "success"
                    })
                    
                except Exception as e:
                    stats["errors"].append(f"{filename}: {str(e)}")
                    stats["details"].append({
                        "old": old_path,
                        "error": str(e),
                        "status": "failed"
                    })
        
        return stats

    @staticmethod
    def relocate_files(old_root: str, new_root: str, db, 
                       progress_callback=None):
        """
        Relocate all MWQ files from old_root to new_root.
        
        Simultaneously:
        1. Copy files to new location
        2. Rename to UUID-based naming if needed
        3. Update database paths
        
        Returns migration statistics.
        """
        if not os.path.exists(old_root):
            return {"error": "Old root folder does not exist", "relocated": 0}
        
        # Create new root if needed
        os.makedirs(new_root, exist_ok=True)
        
        stats = {
            "scanned": 0,
            "relocated": 0,
            "errors": [],
            "details": []
        }
        
        # Find all .mwq files in old location
        mwq_files = []
        for root, _, files in os.walk(old_root):
            for filename in files:
                if filename.lower().endswith(FileManager.MWQ_EXTENSION):
                    mwq_files.append(os.path.join(root, filename))
        
        total = len(mwq_files)
        
        for i, old_path in enumerate(mwq_files):
            stats["scanned"] += 1
            
            if progress_callback:
                progress_callback(f"Migration: {i+1}/{total} - {os.path.basename(old_path)}")
            
            try:
                filename = os.path.basename(old_path)
                
                # Generate UUID-based filename if not already present
                if FileManager.extract_uuid_from_filename(filename):
                    # Already UUID-named, just copy
                    new_filename = filename
                else:
                    # Migrate to UUID naming
                    new_filename = FileManager.generate_mwq_filename(use_uuid=True)
                
                new_path = os.path.join(new_root, new_filename)
                
                # Ensure uniqueness
                counter = 1
                base_name, ext = os.path.splitext(new_filename)
                while os.path.exists(new_path):
                    new_filename = f"{base_name}_{counter}{ext}"
                    new_path = os.path.join(new_root, new_filename)
                    counter += 1
                
                # Copy file (not move - keep original)
                shutil.copy2(old_path, new_path)
                
                # Update database
                if db:
                    db.update_filepath(old_path, new_path)
                
                stats["relocated"] += 1
                stats["details"].append({
                    "old": old_path,
                    "new": new_path,
                    "status": "success"
                })
                
            except Exception as e:
                stats["errors"].append(f"{os.path.basename(old_path)}: {str(e)}")
                stats["details"].append({
                    "old": old_path,
                    "error": str(e),
                    "status": "failed"
                })
        
        return stats

    @staticmethod
    def get_all_mwq_files(root_folder: str) -> List[str]:
        """Get list of all .mwq files in root folder and subdirectories."""
        mwq_files = []
        
        if not os.path.exists(root_folder):
            return mwq_files
        
        for root, _, files in os.walk(root_folder):
            for filename in files:
                if filename.lower().endswith(FileManager.MWQ_EXTENSION):
                    mwq_files.append(os.path.join(root, filename))
        
        return mwq_files

    @staticmethod
    def estimate_size(filepath: str) -> int:
        """Get file size in bytes."""
        try:
            return os.path.getsize(filepath)
        except OSError:
            return 0

    @staticmethod
    def check_file_exists_and_accessible(filepath: str) -> bool:
        """Check if file exists and can be read."""
        return os.path.exists(filepath) and os.path.isfile(filepath) and os.access(filepath, os.R_OK)
