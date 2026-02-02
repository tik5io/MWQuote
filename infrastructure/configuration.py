# infrastructure/configuration.py
import json
import os
from typing import List

class ConfigurationService:
    """Service to load and manage application configuration."""

    def __init__(self, config_path: str = None):
        if config_path is None:
            # Default to same directory as persistence
            base_dir = os.path.dirname(__file__)
            config_path = os.path.join(base_dir, "app_config.json")
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> dict:
        if not os.path.exists(self.config_path):
            return {"cost_typologies": [], "project_tags": []}
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"cost_typologies": [], "project_tags": []}

    def get_cost_typologies(self) -> List[str]:
        return self.config.get("cost_typologies", [])

    def get_project_tags(self) -> List[str]:
        return self.config.get("project_tags", [])
