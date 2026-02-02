
import wx
from core.app_initializer import initialize_app

# Initialize core services and path
initialize_app()

from ui.frames.search_frame import SearchFrame

class AnalysisApp(wx.App):
    def OnInit(self):
        self.frame = SearchFrame()
        self.SetTopWindow(self.frame)
        return True

if __name__ == "__main__":
    app = AnalysisApp()
    app.MainLoop()
