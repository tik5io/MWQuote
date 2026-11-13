#!/usr/bin/env python3
"""
MWProjet - Application principale
Point d'entrée de l'application de gestion des devis.

Modules disponibles:
- Recherche et analyse des projets existants
- Création et édition de nouvelles quotes (QuoteEditor)
- Comparaison de projets
"""

import sys
import os
import traceback

_crash_file = None


def _install_crash_trace():
    """Trace des plantages dans %LOCALAPPDATA%\\MWQuote\\crash.log (jamais effacé par la fermeture normale).

    - faulthandler : les plantages natifs (wxWidgets) laissent au moins la pile Python au moment de l'accident ;
    - excepthook : les exceptions non rattrapées dans un gestionnaire d'événement y sont aussi écrites.
    """
    global _crash_file
    try:
        import faulthandler
        import datetime
        folder = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MWQuote")
        os.makedirs(folder, exist_ok=True)
        _crash_file = open(os.path.join(folder, "crash.log"), "a", encoding="utf-8")
        _crash_file.write(f"\n--- session {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
        _crash_file.flush()
        faulthandler.enable(file=_crash_file, all_threads=True)

        previous = sys.excepthook

        def hook(exc_type, exc, tb):
            try:
                traceback.print_exception(exc_type, exc, tb, file=_crash_file)
                _crash_file.flush()
            finally:
                previous(exc_type, exc, tb)

        sys.excepthook = hook
    except Exception:
        pass                                    # la trace est un confort : jamais bloquante


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
        _install_crash_trace()

        from ui.frames.search_frame import SearchFrame

        # 4. Run application
        class MWProjetApp(wx.App):
            def OnInit(self):
                wx.InitAllImageHandlers()
                self.frame = SearchFrame()
                self.SetTopWindow(self.frame)
                return True

        app = MWProjetApp()
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
            wx.MessageBox(error_msg, "MWProjet - Startup Failure", wx.OK | wx.ICON_ERROR)
        except:
            # Fallback to simple file write if wx failed too
            with open("CRASH_REPORT.txt", "w") as f:
                f.write(error_msg)
        sys.exit(1)

if __name__ == "__main__":
    main()
