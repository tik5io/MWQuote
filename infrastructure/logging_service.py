"""
Logger multi-fichiers pour séparer logs détaillés et log principal.

Ce module permet de créer des loggers qui écrivent:
- Les logs détaillés itératifs dans un fichier dédié (ex: gcode_generation.log)
- Les événements importants dans le log principal (debug.log) avec liens

Usage:
    gcode_logger = ModuleFileLogger("GCodeGen", "gcode_generation.log")
    gcode_logger.detail("[ISO-WRITE] line=5 ...")  # → gcode_generation.log uniquement
    gcode_logger.info("G-code generated")  # → debug.log + gcode_generation.log

Configuration:
    # Désactiver tous les logs (console + fichiers)
    from core.logging import disable_all_logging
    disable_all_logging()
"""

import logging
from pathlib import Path
import sys

# Constantes
ROOT_LOGGER_NAME = "MWQuote"

# Détecte si on est dans l'exécutable PyInstaller
IS_DIST = hasattr(sys, "_MEIPASS")

# Variable globale pour désactiver TOUS les logs (y compris console)
_LOGGING_DISABLED = IS_DIST  # Par défaut, désactivé si exécutable

class ModuleFileLogger:
    """
    Logger qui écrit dans un fichier dédié + log principal.

    Permet de séparer les logs verbeux (itérations, mappings) dans des fichiers
    dédiés tout en gardant les événements importants dans le log principal.
    """

    def __init__(self, module_name: str, detail_filename: str):
        self.module_name = module_name
        self.detail_filename = detail_filename

        # Si logging désactivé globalement, utiliser des NullHandlers partout
        if _LOGGING_DISABLED:
            self.main_logger = logging.getLogger(ROOT_LOGGER_NAME)
            self.main_logger.setLevel(logging.CRITICAL + 1)  # Bloquer tout
            if not self.main_logger.hasHandlers():
                self.main_logger.addHandler(logging.NullHandler())

            self.detail_logger = logging.getLogger(f"{ROOT_LOGGER_NAME}.{module_name}.detail")
            self.detail_logger.setLevel(logging.CRITICAL + 1)  # Bloquer tout
            self.detail_logger.propagate = False
            if not self.detail_logger.hasHandlers():
                self.detail_logger.addHandler(logging.NullHandler())
            return

        # Logger principal (toujours actif si logging enabled)
        self.main_logger = logging.getLogger(ROOT_LOGGER_NAME)
        self.main_logger.setLevel(logging.DEBUG)
        if not self.main_logger.hasHandlers():
            # Création d'un handler console SEULEMENT pour WARNING et au-dessus
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', '%H:%M:%S')
            )
            console_handler.setLevel(logging.WARNING)  # Seulement WARNING, ERROR, CRITICAL
            self.main_logger.addHandler(console_handler)

        # Logger détaillé (désactivé en version distribuée)
        self.detail_logger = logging.getLogger(f"{ROOT_LOGGER_NAME}.{module_name}.detail")
        self.detail_logger.setLevel(logging.DEBUG)
        self.detail_logger.propagate = False

        if not IS_DIST:
            # Créer le dossier de logs si nécessaire
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)

            # Utiliser uniquement le nom du fichier (pas de sous-dossiers)
            log_filename = Path(detail_filename).name
            log_path = log_dir / log_filename

            # Handler pour fichier détaillé
            detail_handler = logging.FileHandler(str(log_path), mode='w', encoding='utf-8')
            detail_formatter = logging.Formatter(
                '%(asctime)s [%(levelname)s]: %(message)s',
                datefmt='%H:%M:%S'
            )
            detail_handler.setFormatter(detail_formatter)
            detail_handler.setLevel(logging.DEBUG)

            if not self.detail_logger.hasHandlers():
                self.detail_logger.addHandler(detail_handler)
        else:
            # Version dist: désactive complètement les logs détaillés
            self.detail_logger.addHandler(logging.NullHandler())

    def detail(self, message: str):
        """Log détaillé dans fichier dédié uniquement (désactivé en dist)."""
        self.detail_logger.debug(message)

    def debug(self, message: str):
        """Log debug dans fichier détaillé uniquement (pas de console)."""
        self.detail_logger.debug(message)

    def info(self, message: str, link_to_detail: bool = False):
        """Log info dans fichier détaillé uniquement (pas de console)."""
        self.detail_logger.info(message)

    def warning(self, message: str):
        """Log warning dans fichier détaillé + console."""
        self.detail_logger.warning(message)
        self.main_logger.warning(f"[{self.module_name}] {message}")

    def error(self, message: str, exc_info: bool = False):
        """Log error dans fichier détaillé + console."""
        self.detail_logger.error(message, exc_info=exc_info)
        self.main_logger.error(f"[{self.module_name}] {message}", exc_info=exc_info)

    def exception(self, message: str):
        """Log exception avec traceback complet dans fichier détaillé + console."""
        self.detail_logger.exception(message)
        self.main_logger.exception(f"[{self.module_name}] {message}")

    def isEnabledFor(self, level: int) -> bool:
        """Vérifie si le logger est activé pour un niveau donné."""
        return self.detail_logger.isEnabledFor(level)

    def section_header(self, title: str, width: int = 80):
        """Écrit un header de section dans le fichier détaillé."""
        self.detail("")
        self.detail("=" * width)
        self.detail(title.center(width))
        self.detail("=" * width)
        self.detail("")

    def close(self):
        """Ferme les handlers de fichiers."""
        for handler in self.detail_logger.handlers:
            handler.close()
            self.detail_logger.removeHandler(handler)


# Instance globale pour faciliter l'usage (optionnel)
_module_loggers = {}

def get_module_logger(module_name: str, detail_filename: str) -> ModuleFileLogger:
    """Récupère ou crée un logger module (cache pour éviter doublons)."""
    key = f"{module_name}:{detail_filename}"
    if key not in _module_loggers:
        _module_loggers[key] = ModuleFileLogger(module_name, detail_filename)
    return _module_loggers[key]

def close_all_module_loggers():
    """Ferme tous les loggers modules créés."""
    for logger in _module_loggers.values():
        logger.close()
    _module_loggers.clear()

def emoji(symbol: str) -> str:
    """Retourne un emoji pour les logs (utilitaire visuel)."""
    return symbol

def disable_all_logging():
    """
    Désactive TOUS les logs (console + fichiers).

    Utile pour:
    - Exécutables PyInstaller (évite de créer un dossier logs/)
    - Mode production
    - Tests unitaires
    """
    global _LOGGING_DISABLED
    _LOGGING_DISABLED = True

def enable_logging():
    """
    Réactive les logs.

    Note: Les loggers déjà créés ne seront pas affectés.
    Seulement les nouveaux loggers créés après cet appel auront les logs activés.
    """
    global _LOGGING_DISABLED
    _LOGGING_DISABLED = False

def is_logging_disabled() -> bool:
    """Retourne True si les logs sont désactivés."""
    return _LOGGING_DISABLED

def clear_logs_directory():
    """
    Vide complètement le dossier logs/.

    Cette fonction:
    - Supprime tous les fichiers .log dans le dossier logs/
    - Ne supprime pas le dossier logs/ lui-même
    - Est silencieuse en cas d'erreur (utile à la fermeture de l'app)
    """
    try:
        log_dir = Path("./logs")
        if not log_dir.exists():
            return

        # Supprimer tous les fichiers .log
        for log_file in log_dir.glob("*.log"):
            try:
                log_file.unlink()
            except Exception:
                pass  # Ignorer les erreurs (fichier verrouillé, etc.)

    except Exception:
        pass  # Ignorer toutes les erreurs
