import wx
import os
import base64
import tempfile
from domain.document import Document

class DocumentListPanel(wx.Panel):
    """Reusable panel to manage a list of Documents (PDFs)."""
    
    def __init__(self, parent, label="Documents :"):
        super().__init__(parent)
        self.documents = []
        self.on_changed = None # Callback when docs are added/removed
        
        self._build_ui(label)

    def _build_ui(self, label):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(self, label=label)
        lbl.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        header_sizer.Add(lbl, 1, wx.ALIGN_CENTER_VERTICAL)
        
        add_btn = wx.Button(self, label="+ Ajouter PDF", size=(100, -1))
        add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        header_sizer.Add(add_btn, 0)
        
        main_sizer.Add(header_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)
        
        # Scrollable list of documents
        self.list_panel = wx.Panel(self)
        self.list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.list_panel.SetSizer(self.list_sizer)
        
        main_sizer.Add(self.list_panel, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

    def load_documents(self, documents):
        self.documents = documents if documents is not None else []
        self._refresh_list()

    def _refresh_list(self):
        self.list_sizer.Clear(True)
        
        if not self.documents:
            empty_lbl = wx.StaticText(self.list_panel, label="Aucun document")
            empty_lbl.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
            self.list_sizer.Add(empty_lbl, 0, wx.ALL, 5)
        else:
            for idx, doc in enumerate(self.documents):
                doc_row = wx.BoxSizer(wx.HORIZONTAL)
                
                # File icon/name
                name_lbl = wx.StaticText(self.list_panel, label=f"📄 {doc.filename}")
                doc_row.Add(name_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
                
                # View button
                view_btn = wx.Button(self.list_panel, label="Voir", size=(50, 22))
                view_btn.Bind(wx.EVT_BUTTON, lambda e, d=doc: self._on_view(d))
                doc_row.Add(view_btn, 0, wx.LEFT, 5)
                
                # Delete button
                del_btn = wx.Button(self.list_panel, label="X", size=(25, 22))
                del_btn.SetForegroundColour(wx.Colour(200, 0, 0))
                del_btn.Bind(wx.EVT_BUTTON, lambda e, i=idx: self._on_delete(i))
                doc_row.Add(del_btn, 0, wx.LEFT, 2)
                
                self.list_sizer.Add(doc_row, 0, wx.EXPAND | wx.BOTTOM, 2)
        
        self.list_panel.Layout()
        self.Layout()
        
        # Force parent and top-level layout refresh
        parent = self.GetParent()
        while parent:
            parent.Layout()
            if isinstance(parent, wx.ScrolledWindow):
                parent.FitInside()
            parent = parent.GetParent()
            
        # Notify parent if something changed
        if self.on_changed:
            self.on_changed()

    def _on_add(self, event):
        with wx.FileDialog(self, "Sélectionner un PDF", wildcard="Fichiers PDF (*.pdf)|*.pdf",
                          style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            
            paths = fileDialog.GetPaths()
            for path in paths:
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                        new_doc = Document(
                            filename=os.path.basename(path),
                            data=base64.b64encode(data).decode('utf-8')
                        )
                        self.documents.append(new_doc)
                except Exception as e:
                    wx.MessageBox(f"Erreur lors de l'ajout de {path}: {e}", "Erreur", wx.OK | wx.ICON_ERROR)
            
            self._refresh_list()

    def _on_delete(self, index):
        if 0 <= index < len(self.documents):
            del self.documents[index]
            self._refresh_list()

    def _on_view(self, doc):
        try:
            suffix = os.path.splitext(doc.filename)[1] or ".pdf"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                data = base64.b64decode(doc.data)
                tmp.write(data)
                tmp_path = tmp.name
            os.startfile(tmp_path)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'ouverture du document : {e}", "Erreur", wx.OK | wx.ICON_ERROR)
