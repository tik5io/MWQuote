#!/usr/bin/env python3
"""
QuoteEditor - Module d'édition des quotes

Ce module fournit les fonctions pour créer et éditer des quotes.
Il est appelé par analysis_app.py (point d'entrée principal).
"""

import os

import wx
from domain.project import Project
from ui.frames.main_frame import MainFrame
from infrastructure.persistence import PersistenceService


# Fiches projet ouvertes : plusieurs fiches peuvent coexister (comparaison),
# mais jamais deux fois le même fichier (deux sauvegardes concurrentes s'écraseraient).
_open_editors = []


def _same_file(a, b):
    try:
        return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def open_editors():
    """Fiches projet encore ouvertes."""
    alive = []
    for frame in _open_editors:
        try:
            if frame and not frame.IsBeingDeleted():
                alive.append(frame)
        except RuntimeError:
            pass   # fenêtre déjà détruite
    _open_editors[:] = alive
    return list(alive)


def find_open_editor(filepath):
    """Fiche déjà ouverte sur ce fichier (son chemin courant, qui suit les « Enregistrer sous »)."""
    for frame in open_editors():
        if _same_file(getattr(frame, "current_path", None), filepath):
            return frame
    return None


def _bring_to_front(frame):
    if frame.IsIconized():
        frame.Iconize(False)
    frame.Raise()
    frame.SetFocus()


def _setup_modal_behavior(editor_frame, parent_frame):
    """Rattache la fiche à la fenêtre liste, SANS la bloquer.

    La liste reste utilisable pour ouvrir d'autres fiches ; à la fermeture d'une
    fiche, elle est rafraîchie (et sélectionne un projet nouvellement créé).
    """
    _open_editors.append(editor_frame)
    if not parent_frame:
        return

    def on_editor_closed(created_filepath):
        # Appelé par la fiche à la fin de sa fermeture réelle (après l'éventuelle
        # sauvegarde et l'indexation ; jamais si l'utilisateur annule).
        open_editors()   # purge la fiche fermée du registre
        try:
            if hasattr(parent_frame, '_refresh_list'):
                parent_frame._refresh_list()
            if created_filepath and hasattr(parent_frame, '_select_and_display_quote'):
                parent_frame._select_and_display_quote(created_filepath)
        except RuntimeError:
            return  # fenêtre parente déjà détruite
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Rafraîchissement de la liste après fermeture")

    editor_frame.on_closed = on_editor_closed


def tile_side_by_side(frames):
    """Range les fiches côte à côte sur l'écran de la première (comparaison)."""
    frames = [f for f in frames if f]
    if not frames:
        return
    display = wx.Display.GetFromWindow(frames[0])
    area = wx.Display(display if display != wx.NOT_FOUND else 0).GetClientArea()
    width = area.width // len(frames)
    for i, frame in enumerate(frames):
        if frame.IsMaximized():
            frame.Maximize(False)
        frame.SetSize(area.x + i * width, area.y, width, area.height)
        frame.Raise()


def open_new_quote(parent_frame=None, parent_indexer=None):
    """
    Ouvre l'éditeur avec une nouvelle quote vide.

    Args:
        parent_frame: Fenêtre liste (reste active ; rafraîchie à la fermeture)
        parent_indexer: Indexer optionnel pour l'auto-indexation lors de la sauvegarde

    Returns:
        MainFrame: La fenêtre de l'éditeur créée
    """
    new_project = Project(name="", reference="", client="")
    editor_frame = MainFrame(project=new_project, clear_logs=False, filepath=None, new_quote=True)

    _setup_modal_behavior(editor_frame, parent_frame)

    editor_frame.Raise()
    return editor_frame


def open_quote_from_file(filepath, parent_frame=None, parent_indexer=None):
    """
    Ouvre l'éditeur avec un projet chargé depuis un fichier.

    Args:
        filepath: Chemin vers le fichier .mwq à ouvrir
        parent_frame: Fenêtre liste (reste active ; rafraîchie à la fermeture)
        parent_indexer: Indexer optionnel pour l'auto-indexation

    Returns:
        MainFrame: La fenêtre de l'éditeur créée (ou celle déjà ouverte sur ce fichier)

    Raises:
        Exception: Si le chargement du fichier échoue
    """
    existing = find_open_editor(filepath)
    if existing:
        _bring_to_front(existing)
        return existing

    project = PersistenceService.load_project(filepath)
    editor_frame = MainFrame(project=project, clear_logs=False, filepath=filepath)

    _setup_modal_behavior(editor_frame, parent_frame)

    # Auto-index si un indexer est fourni
    if parent_indexer:
        parent_indexer.index_file(filepath)

    editor_frame.Raise()
    return editor_frame


def open_quote_from_project(project, filepath=None, parent_frame=None):
    """
    Ouvre l'éditeur avec un projet déjà chargé.

    Args:
        project: Instance de Project à éditer
        filepath: Chemin optionnel du fichier source
        parent_frame: Fenêtre liste (reste active ; rafraîchie à la fermeture)

    Returns:
        MainFrame: La fenêtre de l'éditeur créée
    """
    editor_frame = MainFrame(project=project, clear_logs=False, filepath=filepath)

    _setup_modal_behavior(editor_frame, parent_frame)

    editor_frame.Raise()
    return editor_frame


# Permet aussi de lancer directement le module pour test/debug
if __name__ == "__main__":
    from core.app_initializer import initialize_app
    initialize_app()

    app = wx.App()
    wx.InitAllImageHandlers()
    open_new_quote()
    app.MainLoop()
