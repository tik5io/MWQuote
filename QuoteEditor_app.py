#!/usr/bin/env python3
"""
QuoteEditor - Module d'édition des quotes

Ce module fournit les fonctions pour créer et éditer des quotes.
Il est appelé par analysis_app.py (point d'entrée principal).
"""

import wx
from domain.project import Project
from ui.frames.main_frame import MainFrame
from infrastructure.persistence import PersistenceService


def _setup_modal_behavior(editor_frame, parent_frame):
    """
    Configure le comportement modal de l'éditeur par rapport au parent.
    Désactive le parent et le réactive à la fermeture de l'éditeur.
    """
    if not parent_frame:
        return

    parent_frame.Disable()

    def on_editor_close(event):
        parent_frame.Enable()
        parent_frame.Raise()
        # Rafraîchir la liste si le parent a cette méthode
        if hasattr(parent_frame, '_refresh_list'):
            parent_frame._refresh_list()
        event.Skip()

    editor_frame.Bind(wx.EVT_CLOSE, on_editor_close)


def open_new_quote(parent_frame=None, parent_indexer=None):
    """
    Ouvre l'éditeur avec une nouvelle quote vide.

    Args:
        parent_frame: Fenêtre parente (sera désactivée pendant l'édition)
        parent_indexer: Indexer optionnel pour l'auto-indexation lors de la sauvegarde

    Returns:
        MainFrame: La fenêtre de l'éditeur créée
    """
    new_project = Project(name="Nouveau Projet", reference="", client="")
    editor_frame = MainFrame(project=new_project, clear_logs=False, filepath=None)

    _setup_modal_behavior(editor_frame, parent_frame)

    editor_frame.Raise()
    return editor_frame


def open_quote_from_file(filepath, parent_frame=None, parent_indexer=None):
    """
    Ouvre l'éditeur avec un projet chargé depuis un fichier.

    Args:
        filepath: Chemin vers le fichier .mwq à ouvrir
        parent_frame: Fenêtre parente (sera désactivée pendant l'édition)
        parent_indexer: Indexer optionnel pour l'auto-indexation

    Returns:
        MainFrame: La fenêtre de l'éditeur créée

    Raises:
        Exception: Si le chargement du fichier échoue
    """
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
        parent_frame: Fenêtre parente (sera désactivée pendant l'édition)

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
