# ui/panels/project_panel.py
import wx

class ProjectPanel(wx.Panel):

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self._build_ui()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(self, label="Projet"), 0, wx.ALL, 5)

        self.ref_ctrl = wx.TextCtrl(self)
        self.client_ctrl = wx.TextCtrl(self)

        sizer.Add(wx.StaticText(self, label="Référence"), 0, wx.ALL, 5)
        sizer.Add(self.ref_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        sizer.Add(wx.StaticText(self, label="Client"), 0, wx.ALL, 5)
        sizer.Add(self.client_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        self.save_btn = wx.Button(self, label="Sauvegarder projet")
        self.save_btn.Bind(wx.EVT_BUTTON, lambda e: self.save_project())
        sizer.Add(self.save_btn, 0, wx.ALL, 5)

        self.SetSizer(sizer)

    def load_project(self, project):
        self.project = project
        self.ref_ctrl.SetValue(project.reference)
        self.client_ctrl.SetValue(project.client)

    def save_project(self):
        if self.project:
            self.project.reference = self.ref_ctrl.GetValue()
            self.project.client = self.client_ctrl.GetValue()
