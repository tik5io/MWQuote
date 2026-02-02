# ui/dialogs/tiers_editor_dialog.py
import wx
import copy
from domain.cost import PricingTier

class TiersEditorDialog(wx.Dialog):
    def __init__(self, parent, tiers):
        super().__init__(parent, title="Échelons", size=(400, 300))
        self.tiers = copy.deepcopy(tiers)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.InsertColumn(0, "Min", width=60)
        self.list.InsertColumn(1, "Max", width=60)
        self.list.InsertColumn(2, "Unit (€)", width=100)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        
        hint = wx.StaticText(self, label="Double-cliquez pour éditer un échelon")
        hint.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        sizer.Add(hint, 0, wx.LEFT, 10)
        btns = wx.BoxSizer(wx.HORIZONTAL)
        add = wx.Button(self, label="+")
        add.Bind(wx.EVT_BUTTON, self._on_add)
        btns.Add(add)
        rem = wx.Button(self, label="X")
        rem.Bind(wx.EVT_BUTTON, self._on_del)
        btns.Add(rem)
        sizer.Add(btns, 0, wx.ALIGN_CENTER)
        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_CENTER | wx.ALL, 5)
        self.SetSizer(sizer)
        self._refresh()

    def _refresh(self):
        self.list.DeleteAllItems()
        self.tiers.sort(key=lambda x: x.min_quantity)
        for i, t in enumerate(self.tiers):
            # Calculate Max based on next tier
            if i + 1 < len(self.tiers):
                max_val = str(self.tiers[i+1].min_quantity - 1)
            else:
                max_val = "∞"
                
            self.list.InsertItem(i, str(t.min_quantity))
            self.list.SetItem(i, 1, max_val)
            self.list.SetItem(i, 2, f"{t.unit_price:.2f}")

    def _on_add(self, event):
        dlg = SingleTierDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            # Check if min_quantity already exists
            new_tier = dlg.get_tier()
            self.tiers = [t for t in self.tiers if t.min_quantity != new_tier.min_quantity]
            self.tiers.append(new_tier)
            self._refresh()
        dlg.Destroy()

    def _on_edit(self, event):
        idx = self.list.GetFirstSelected()
        if idx == -1: return
        
        # We find the tier by its min_val (which is the unique identifier here)
        min_val = int(self.list.GetItemText(idx))
        tier = next((t for t in self.tiers if t.min_quantity == min_val), None)
        if not tier: return
        
        dlg = SingleTierDialog(self, tier)
        if dlg.ShowModal() == wx.ID_OK:
            new_tier = dlg.get_tier()
            # If min_quantity changed, remove the old one first
            self.tiers = [t for t in self.tiers if t.min_quantity != min_val]
            # Remove any existing tier with the NEW min_quantity too
            self.tiers = [t for t in self.tiers if t.min_quantity != new_tier.min_quantity]
            self.tiers.append(new_tier)
            self._refresh()
        dlg.Destroy()

    def _on_del(self, event):
        idx = self.list.GetFirstSelected()
        if idx != -1:
            val = int(self.list.GetItemText(idx))
            self.tiers = [t for t in self.tiers if t.min_quantity != val]
            self._refresh()

    def get_tiers(self):
        return sorted(self.tiers, key=lambda x: x.min_quantity)

class SingleTierDialog(wx.Dialog):
    def __init__(self, parent, tier=None):
        super().__init__(parent, title="Échelon")
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
        grid.Add(wx.StaticText(self, label="Min:"))
        self.min = wx.SpinCtrl(self, initial=tier.min_quantity if tier else 0, max=1000000)
        grid.Add(self.min)
        grid.Add(wx.StaticText(self, label="Unit (€):"))
        self.val = wx.TextCtrl(self, value=f"{tier.unit_price:.2f}" if tier else "0.00")
        grid.Add(self.val)
        sizer.Add(grid, 1, wx.ALL, 10)
        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL, 5)
        self.SetSizer(sizer)

    def get_tier(self):
        return PricingTier(min_quantity=self.min.GetValue(), unit_price=float(self.val.GetValue()))
