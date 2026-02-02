import wx

class QuantityManagerDialog(wx.Dialog):
    def __init__(self, parent, quantities):
        super().__init__(parent, title="Gestion des quantités", size=(300, 400))
        self.quantities = sorted(list(quantities))
        self._init_ui()

    def _init_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.list = wx.ListBox(self)
        self._refresh_list()
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(self, label="+")
        add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        btn_sizer.Add(add_btn, 0, wx.ALL, 5)
        
        del_btn = wx.Button(self, label="Supprimer")
        del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        btn_sizer.Add(del_btn, 0, wx.ALL, 5)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER)
        
        db_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(db_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        self.SetSizer(sizer)

    def _refresh_list(self):
        self.list.Clear()
        for q in sorted(self.quantities):
            self.list.Append(str(q))

    def _on_add(self, event):
        dlg = wx.TextEntryDialog(self, "Entrez une nouvelle quantité :", "Ajouter")
        if dlg.ShowModal() == wx.ID_OK:
            try:
                qty = int(dlg.GetValue())
                if qty > 0 and qty not in self.quantities:
                    self.quantities.append(qty)
                    self._refresh_list()
            except ValueError:
                wx.MessageBox("Entier valide requis", "Erreur")
        dlg.Destroy()

    def _on_delete(self, event):
        sel = self.list.GetSelection()
        if sel != wx.NOT_FOUND:
            val = int(self.list.GetString(sel))
            self.quantities.remove(val)
            self._refresh_list()

    def get_quantities(self):
        return sorted(self.quantities)
