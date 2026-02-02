
import wx
from core.app_initializer import initialize_app

# Initialize core services and path
initialize_app()

from ui.frames.main_frame import MainFrame

class QuoteEditorApp(wx.App):
    def OnInit(self):
        self.frame = MainFrame(project=None, clear_logs=True)
        self.SetTopWindow(self.frame)
        return True

if __name__ == "__main__":
    app = QuoteEditorApp()
    app.MainLoop()