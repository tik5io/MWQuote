import wx
import os
import base64
import tempfile
from domain.document import Document
from ui.components.ribbon_button import RibbonButton, ACCENT

class DocumentListPanel(wx.Panel):
    """Reusable panel to manage a list of Documents (PDFs)."""

    def __init__(self, parent, label="Documents :", project_name_callback=None):
        super().__init__(parent)
        self.documents = []
        self.on_changed = None
        self.project_name_callback = project_name_callback
        self._temp_files = []  # Track temporary files for cleanup
        self._read_only = False
        self._locked = False          # version figée : seuls Voir/Exporter restent actifs
        self._delete_btns = []        # boutons « X » des lignes (désactivés si figé)

        self._build_ui(label)

    def set_read_only(self, read_only: bool):
        """Lecture seule : « Voir » et « Exporter » restent actifs, ni ajout ni suppression."""
        read_only = bool(read_only)
        if read_only == self._read_only:
            return
        self._read_only = read_only
        self.add_btn.Show(not read_only)
        self._refresh_list()

    def _build_ui(self, label):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        header_sizer = wx.WrapSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(self, label=label)
        lbl.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        header_sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        
        self.add_btn = RibbonButton(self, "📎", "Ajouter un PDF", accent=ACCENT, size=(150, 36))
        self.add_btn.SetToolTip("Joindre un ou plusieurs fichiers PDF")
        self.add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self.add_btn.Enable(not self._locked)
        header_sizer.Add(self.add_btn, 0)
        
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

    def set_locked(self, locked: bool) -> None:
        """Version figée : on ne peut plus ajouter ni supprimer de PDF.

        Les boutons « Voir » et « Exporter » restent actifs (consultation du devis
        figé). La liste n'est pas reconstruite ici pour ne pas déclencher on_changed ;
        seuls les boutons concernés sont (dés)activés.
        """
        self._locked = bool(locked)
        try:
            self.add_btn.Enable(not self._locked)
        except RuntimeError:
            pass
        for btn in self._delete_btns:
            try:
                btn.Enable(not self._locked)
            except RuntimeError:
                pass

    def _refresh_list(self):
        self.list_sizer.Clear(True)
        self._delete_btns = []

        if not self.documents:
            empty_lbl = wx.StaticText(self.list_panel, label="Aucun document")
            empty_lbl.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
            self.list_sizer.Add(empty_lbl, 0, wx.ALL, 5)
        else:
            for idx, doc in enumerate(self.documents):
                # Un document = deux lignes : le nom (abrégé AU MILIEU pour garder l'extension, nom
                # complet en infobulle) puis ses boutons. Un long nom ne pousse donc plus les boutons
                # hors du panneau.
                item = wx.BoxSizer(wx.VERTICAL)
                name_lbl = wx.StaticText(self.list_panel, label=f"📄 {doc.filename}", style=wx.ST_ELLIPSIZE_MIDDLE)
                name_lbl.SetMinSize((10, -1))
                name_lbl.SetToolTip(doc.filename)
                item.Add(name_lbl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)

                doc_row = wx.BoxSizer(wx.HORIZONTAL)
                item.AddSpacer(3)
                item.Add(doc_row, 0, wx.LEFT, 20)

                view_btn = wx.Button(self.list_panel, label="Voir", size=(50, 22))
                view_btn.Bind(wx.EVT_BUTTON, lambda e, d=doc: self._on_view(d))
                doc_row.Add(view_btn, 0)

                exp_btn = wx.Button(self.list_panel, label="Exporter", size=(70, 22))
                exp_btn.Bind(wx.EVT_BUTTON, lambda e, d=doc: self._on_export(d))
                doc_row.Add(exp_btn, 0, wx.LEFT, 4)

                # Delete button (absent en lecture seule : gamme figée, consultation uniquement ;
                # désactivé si la version est figée)
                if not self._read_only:
                    del_btn = wx.Button(self.list_panel, label="X", size=(25, 22))
                    del_btn.SetForegroundColour(wx.Colour(200, 0, 0))
                    del_btn.Bind(wx.EVT_BUTTON, lambda e, i=idx: self._on_delete(i))
                    del_btn.Enable(not self._locked)
                    self._delete_btns.append(del_btn)
                    doc_row.Add(del_btn, 0, wx.LEFT, 4)

                self.list_sizer.Add(item, 0, wx.EXPAND | wx.BOTTOM, 6)
        
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
        if self._locked:
            return
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
        if self._locked:
            return
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
            # Track this temporary file for later cleanup
            self._temp_files.append(tmp_path)
            os.startfile(tmp_path)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'ouverture du document : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_export(self, doc):
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.isdir(desktop):
                desktop = os.path.expanduser("~")

            # Build default filename from project name + doc filename
            if self.project_name_callback:
                project_name = self.project_name_callback() or ""
            else:
                project_name = ""

            suffix = os.path.splitext(doc.filename)[1] or ".pdf"
            base = os.path.splitext(doc.filename)[0]
            if project_name:
                default_name = f"{project_name} - {base}{suffix}"
            else:
                default_name = doc.filename

            # Sanitize for Windows filename
            for ch in r'\/:*?"<>|':
                default_name = default_name.replace(ch, "_")

            wildcard = "Fichiers PDF (*.pdf)|*.pdf|Tous les fichiers (*.*)|*.*"
            with wx.FileDialog(self, "Enregistrer le document sous",
                               defaultDir=desktop,
                               defaultFile=default_name,
                               wildcard=wildcard,
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
                if dlg.ShowModal() == wx.ID_CANCEL:
                    return
                dest_path = dlg.GetPath()

            data = base64.b64decode(doc.data)
            with open(dest_path, "wb") as f:
                f.write(data)

            wx.MessageBox(f"Document exporté avec succès :\n{dest_path}", "Export réussi", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'export : {e}", "Erreur", wx.OK | wx.ICON_ERROR)

    def cleanup_temp_files(self):
        """Supprime tous les fichiers temporaires créés lors de l'affichage des documents."""
        for tmp_path in self._temp_files:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                # Ignore les erreurs (fichier verrouillé, etc.)
                pass
        self._temp_files.clear()
