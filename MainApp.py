#!/usr/bin/env python3
"""
MWQuote - Application principale
Point d'entrée de l'application de gestion des devis.

Modules disponibles:
- Recherche et analyse des projets existants
- Création et édition de nouvelles quotes (QuoteEditor)
- Comparaison de projets
"""

import sys
import os
import traceback

def main():
    """Point d'entrée principal de l'application"""
    try:
        # 1. Imports inside try to catch import-time errors
        import wx
        from core.app_initializer import initialize_app
        from infrastructure.logging_service import clear_logs_directory

        # 2. Dynamic path handling if frozen
        if hasattr(sys, '_MEIPASS'):
            app_root = sys._MEIPASS
            if app_root not in sys.path:
                sys.path.insert(0, app_root)

        # 3. Initialize components
        initialize_app()
        
        from ui.frames.search_frame import SearchFrame

        # 4. Run application
        class MWQuoteApp(wx.App):
            def OnInit(self):
                wx.InitAllImageHandlers()
                self.frame = SearchFrame()
                self.SetTopWindow(self.frame)
                return True

        app = MWQuoteApp()
        app.MainLoop()
        
        # Cleanup
        clear_logs_directory()

    except Exception as e:
        error_msg = f"CRITICAL STARTUP ERROR:\n\n{str(e)}\n\n{traceback.format_exc()}"
        print(error_msg)
        
        # Try to show a dialog using wx if possible
        try:
            import wx
            if not wx.GetApp():
                temp_app = wx.App()
            wx.MessageBox(error_msg, "MWQuote - Startup Failure", wx.OK | wx.ICON_ERROR)
        except:
            # Fallback to simple file write if wx failed too
            with open("CRASH_REPORT.txt", "w") as f:
                f.write(error_msg)
        sys.exit(1)

if __name__ == "__main__":
    main()
