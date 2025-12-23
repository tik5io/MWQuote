# ui/panels/project_panel.py
import wx
import base64
import os
import tempfile

class ProjectPanel(wx.Panel):
    """Panel for managing project-level information and drawings."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Grid for Info
        grid = wx.FlexGridSizer(cols=4, hgap=10, vgap=10)
        grid.AddGrowableCol(1, 1)
        grid.AddGrowableCol(3, 1)
        
        grid.Add(wx.StaticText(self, label="Référence:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.ref_ctrl = wx.TextCtrl(self)
        self.ref_ctrl.Bind(wx.EVT_TEXT, lambda e: self.save_project())
        grid.Add(self.ref_ctrl, 1, wx.EXPAND)
        
        grid.Add(wx.StaticText(self, label="Client:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.client_ctrl = wx.TextCtrl(self)
        self.client_ctrl.Bind(wx.EVT_TEXT, lambda e: self.save_project())
        grid.Add(self.client_ctrl, 1, wx.EXPAND)
        
        main_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        
        # Drawing Section
        drawing_sizer = wx.BoxSizer(wx.HORIZONTAL)
        drawing_sizer.Add(wx.StaticText(self, label="Plan de la pièce (PDF):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        
        self.drawing_label = wx.StaticText(self, label="Aucun plan attaché")
        self.drawing_label.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        drawing_sizer.Add(self.drawing_label, 1, wx.ALIGN_CENTER_VERTICAL)
        
        self.attach_btn = wx.Button(self, label="Attacher...")
        self.attach_btn.Bind(wx.EVT_BUTTON, self._on_attach_drawing)
        drawing_sizer.Add(self.attach_btn, 0, wx.LEFT, 5)
        
        self.view_btn = wx.Button(self, label="Voir")
        self.view_btn.Bind(wx.EVT_BUTTON, self._on_view_drawing)
        self.view_btn.Disable()
        drawing_sizer.Add(self.view_btn, 0, wx.LEFT, 5)
        
        self.remove_btn = wx.Button(self, label="X")
        self.remove_btn.SetToolTip("Supprimer le plan")
        self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove_drawing)
        self.remove_btn.Disable()
        drawing_sizer.Add(self.remove_btn, 0, wx.LEFT, 5)
        
        main_sizer.Add(drawing_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        self.SetSizer(main_sizer)

    def load_project(self, project):
        self.project = project
        self.ref_ctrl.SetValue(project.reference or "")
        self.client_ctrl.SetValue(project.client or "")
        self._update_drawing_ui()

    def save_project(self):
        """Update the project object with UI values."""
        if self.project:
            self.project.reference = self.ref_ctrl.GetValue()
            self.project.client = self.client_ctrl.GetValue()

    def _update_drawing_ui(self):
        if not self.project: return
        
        if self.project.drawing_filename:
            self.drawing_label.SetLabel(self.project.drawing_filename)
            self.drawing_label.SetForegroundColour(wx.Colour(0, 100, 0)) # Dark Green
            self.view_btn.Enable()
            self.remove_btn.Enable()
        else:
            self.drawing_label.SetLabel("Aucun plan attaché")
            self.drawing_label.SetForegroundColour(wx.BLACK)
            self.view_btn.Disable()
            self.remove_btn.Disable()

    def _on_attach_drawing(self, event):
        with wx.FileDialog(self, "Sélectionner le plan (PDF)", wildcard="Fichiers PDF (*.pdf)|*.pdf",
                          style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            path = fileDialog.GetPath()
            try:
                with open(path, "rb") as f:
                    data = f.read()
                    self.project.drawing_data = base64.b64encode(data).decode('utf-8')
                    self.project.drawing_filename = os.path.basename(path)
                
                self._update_drawing_ui()
                wx.MessageBox("Plan attaché avec succès !", "Information")
            except Exception as e:
                wx.MessageBox(f"Erreur lors de l'attachement : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_remove_drawing(self, event):
        if wx.MessageBox("Supprimer le plan du projet ?", "Confirmation", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.project.drawing_filename = None
            self.project.drawing_data = None
            self._update_drawing_ui()

    def _on_view_drawing(self, event):
        if not self.project or not self.project.drawing_data: return
        
        try:
            # Create a temporary file to open the PDF
            suffix = os.path.splitext(self.project.drawing_filename)[1] or ".pdf"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                data = base64.b64decode(self.project.drawing_data)
                tmp.write(data)
                tmp_path = tmp.name
            
            # Start the file with the default viewer
            os.startfile(tmp_path)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'ouverture du plan : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)
