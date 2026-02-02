#!/usr/bin/env python3
"""
MWQuote - Application principale
Point d'entrée de l'application de gestion des devis.

Modules disponibles:
- Recherche et analyse des projets existants
- Création et édition de nouvelles quotes (QuoteEditor)
- Comparaison de projets
"""

import wx
from core.app_initializer import initialize_app

# Initialize core services and path
initialize_app()

from ui.frames.search_frame import SearchFrame


class MWQuoteApp(wx.App):
    """Application principale MWQuote"""

    def OnInit(self):
        self.frame = SearchFrame()
        self.SetTopWindow(self.frame)
        return True


def main():
    """Point d'entrée principal de l'application"""
    app = MWQuoteApp()
    app.MainLoop()


if __name__ == "__main__":
    main()
