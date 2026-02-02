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
            base_dir = os.path.dirname(__file__)
            config_path = os.path.join(base_dir, "app_config.json")
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
        if not os.path.exists(self.config_path):
            return defaults
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                # Merge with defaults
                for key, value in defaults.items():
                    if key not in loaded:
                        loaded[key] = value
                return loaded
        except Exception:
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
        """Get the configured root folder for quotes."""
        return self.config.get("quotes_root_folder")

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
