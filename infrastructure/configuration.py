# infrastructure/configuration.py
import json
import os
from typing import List, Optional

class ConfigurationService:
    """Service to load and manage application configuration."""

    _instance = None  # Singleton instance

    @classmethod
    def get_instance(cls) -> 'ConfigurationService':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = ConfigurationService()
        return cls._instance

    def __init__(self, config_path: str = None):
        if config_path is None:
            # Persistent config in AppData
            app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))
            db_dir = os.path.join(app_data, "MWQuote")
            os.makedirs(db_dir, exist_ok=True)
            config_path = os.path.join(db_dir, "app_config.json")
        
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> dict:
        defaults = {
            "cost_typologies": [],
            "project_tags": [],
            "quotes_root_folder": None,
            "auto_migrate_on_root_change": True,
            "use_uuid_for_filenames": True
        }
        
        # 1. Try to load from persistent AppData path
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # Merge with basic defaults
                    for key, value in defaults.items():
                        if key not in loaded:
                            loaded[key] = value
                    return loaded
            except Exception:
                pass

        # 2. If AppData config missing or invalid, try to load from bundled assets
        try:
            from core.app_icon import get_bundled_config_path
            bundled_path = get_bundled_config_path()
            if bundled_path.exists():
                with open(bundled_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # Save a copy to AppData for persistence and later modification
                    self.config = loaded
                    self.save()
                    return loaded
        except Exception:
            pass

        # 3. Last resort - use hardcoded defaults
        return defaults

    def save(self):
        """Save configuration to file."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get_cost_typologies(self) -> List[str]:
        return self.config.get("cost_typologies", [])

    def get_project_tags(self) -> List[str]:
        return self.config.get("project_tags", [])

    def get_quotes_root_folder(self) -> Optional[str]:
        """Get the configured root folder for quotes. Defaults to AppData if not set."""
        folder = self.config.get("quotes_root_folder")
        if not folder:
            # Default to AppData/Local/MWQuote/Quotes
            app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))
            folder = os.path.join(app_data, "MWQuote", "Quotes")
            # We don't save it to config yet, just return it as default
            # But we ensure it exists
            os.makedirs(folder, exist_ok=True)
        return folder

    def set_quotes_root_folder(self, folder: str):
        """Set the root folder for quotes."""
        old_folder = self.config.get("quotes_root_folder")
        self.config["quotes_root_folder"] = folder
        self.save()
        return old_folder

    def is_auto_migrate_enabled(self) -> bool:
        """Check if automatic migration is enabled."""
        return self.config.get("auto_migrate_on_root_change", True)

    def set_auto_migrate_enabled(self, enabled: bool):
        """Enable/disable automatic migration on root folder change."""
        self.config["auto_migrate_on_root_change"] = enabled
        self.save()

    def use_uuid_for_filenames(self) -> bool:
        """Check if UUID-based filenames should be used."""
        return self.config.get("use_uuid_for_filenames", True)

    def set_use_uuid_for_filenames(self, use_uuid: bool):
        """Enable/disable UUID-based filenames."""
        self.config["use_uuid_for_filenames"] = use_uuid
        self.save()
