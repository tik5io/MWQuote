
import sys
import os
from infrastructure.logging_service import enable_logging

def initialize_app():
    """Initialise les composants communs de l'application (logging, paths, etc.)"""
    # Ajoute le répertoire courant au path pour les imports
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if app_root not in sys.path:
        sys.path.insert(0, app_root)
    
    # Active les logs
    enable_logging()
