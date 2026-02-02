# ui/panels/project_panel.py
import wx
import wx.adv
import base64
import os
import tempfile
from infrastructure.configuration import ConfigurationService

from ui.dialogs.quantity_manager_dialog import QuantityManagerDialog
from ui.components.document_list_panel import DocumentListPanel

class ProjectPanel(wx.Panel):
    """Panel for managing project-level information and drawings."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.on_quantities_changed = None
        self.config_service = ConfigurationService()
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
        
        grid.Add(wx.StaticText(self, label="Date du projet:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.date_ctrl = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY | wx.adv.DP_ALLOWNONE)
        self.date_ctrl.Bind(wx.adv.EVT_DATE_CHANGED, lambda e: self.save_project())
        grid.Add(self.date_ctrl, 1, wx.EXPAND)
        
        main_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        
        # Drawing Section (Refactored for Multiple PDFs)
        self.doc_list = DocumentListPanel(self, label="Plans de la pièce (PDF) :")
        self.doc_list.on_changed = self.save_project
        main_sizer.Add(self.doc_list, 0, wx.EXPAND | wx.ALL, 10)
        
        # Quantities Section
        qty_sizer = wx.BoxSizer(wx.HORIZONTAL)
        qty_sizer.Add(wx.StaticText(self, label="Quantités de vente:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        
        self.qty_list_ctrl = wx.StaticText(self, label="")
        qty_sizer.Add(self.qty_list_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        
        self.edit_qty_btn = wx.Button(self, label="Gérer les quantités...")
        self.edit_qty_btn.Bind(wx.EVT_BUTTON, self._on_manage_quantities)
        qty_sizer.Add(self.edit_qty_btn, 0, wx.LEFT, 5)
        
        main_sizer.Add(qty_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Milestones Section
        ms_sizer = wx.StaticBoxSizer(wx.VERTICAL, self, "Suivi de l'Offre (Jalons)")
        
        status_box = wx.BoxSizer(wx.HORIZONTAL)
        status_box.Add(wx.StaticText(self, label="Statut actuel :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        
        self.status_choice = wx.Choice(self, choices=["En construction", "Finalisée", "Transmise"])
        self.status_choice.Bind(wx.EVT_CHOICE, self._on_status_changed)
        status_box.Add(self.status_choice, 1, wx.EXPAND)
        
        ms_sizer.Add(status_box, 0, wx.EXPAND | wx.ALL, 5)
        
        self.milestone_info = wx.StaticText(self, label="")
        ms_sizer.Add(self.milestone_info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        main_sizer.Add(ms_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # Tags Section
        tag_sizer = wx.BoxSizer(wx.VERTICAL)
        tag_sizer.Add(wx.StaticText(self, label="Étiquettes de Classification du Projet :"), 0, wx.BOTTOM, 5)
        
        self.tags_wrap_sizer = wx.WrapSizer(wx.HORIZONTAL)
        self.tag_checkboxes = []
        for tag in self.config_service.get_project_tags():
            cb = wx.CheckBox(self, label=tag)
            cb.Bind(wx.EVT_CHECKBOX, lambda e: self.save_project())
            self.tag_checkboxes.append(cb)
            self.tags_wrap_sizer.Add(cb, 0, wx.ALL, 5)
            
        tag_sizer.Add(self.tags_wrap_sizer, 0, wx.EXPAND)
        main_sizer.Add(tag_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        self.SetSizer(main_sizer)

    def load_project(self, project):
        self._is_loading = True
        try:
            self.project = project
            self.ref_ctrl.ChangeValue(project.reference or "")
            self.client_ctrl.ChangeValue(project.client or "")
            
            # Load project date
            if project.project_date:
                try:
                    # Parse ISO format date (YYYY-MM-DD)
                    year, month, day = map(int, project.project_date.split('-'))
                    dt = wx.DateTime()
                    dt.Set(day, month - 1, year)  # month is 0-indexed in wx.DateTime
                    self.date_ctrl.SetValue(dt)
                except (ValueError, AttributeError):
                    pass  # Invalid date format, leave empty
            
            self.doc_list.load_documents(project.documents)
            self._update_qty_ui()
            self._update_tags_ui()
            
            # Load status and milestones
            status = getattr(project, "status", "En construction")
            idx = self.status_choice.FindString(status)
            if idx != wx.NOT_FOUND:
                self.status_choice.SetSelection(idx)
            self._update_milestone_ui()
        finally:
            self._is_loading = False

    def save_project(self):
        """Update the project object with UI values."""
        if getattr(self, "_is_loading", False):
            return
            
        if self.project:
            self.project.reference = self.ref_ctrl.GetValue()
            self.project.client = self.client_ctrl.GetValue()
            
            # Save project date in ISO format
            dt = self.date_ctrl.GetValue()
            if dt.IsValid():
                self.project.project_date = f"{dt.GetYear()}-{dt.GetMonth() + 1:02d}-{dt.GetDay():02d}"
            else:
                self.project.project_date = None
            
            self.project.tags = [cb.GetLabel() for cb in self.tag_checkboxes if cb.GetValue()]
            self.project.documents = self.doc_list.documents
            
            if hasattr(self, "on_project_changed") and self.on_project_changed:
                self.on_project_changed()


    def _update_tags_ui(self):
        if not self.project: return
        # Uncheck all first
        for cb in self.tag_checkboxes:
            cb.SetValue(False)
            
        # Check based on project tags
        for tag in self.project.tags:
            for cb in self.tag_checkboxes:
                if cb.GetLabel() == tag:
                    cb.SetValue(True)
                    break

    def _update_milestone_ui(self):
        if not self.project: return
        dates = getattr(self.project, "status_dates", {})
        info = []
        if dates.get("En construction"): info.append(f"🏗️ Construction: {dates['En construction']}")
        if dates.get("Finalisée"): info.append(f"🏁 Finalisée: {dates['Finalisée']}")
        if dates.get("Transmise"): info.append(f"📧 Transmise: {dates['Transmise']}")
        self.milestone_info.SetLabel(" | ".join(info) if info else "Aucun jalon enregistré")

    def _on_status_changed(self, event):
        if not self.project: return
        new_status = self.status_choice.GetStringSelection()
        
        import datetime
        now_str = datetime.date.today().isoformat()
        
        if not hasattr(self.project, "status_dates"):
            self.project.status_dates = {}
            
        self.project.status = new_status
        # Set date for the new status if not already set (or always update? Let's update to current date when picked)
        self.project.status_dates[new_status] = now_str
        
        self._update_milestone_ui()
        self.save_project()

    def _update_qty_ui(self):
        if not self.project: return
        qtys = sorted(self.project.sale_quantities)
        self.qty_list_ctrl.SetLabel(", ".join(map(str, qtys)) if qtys else "Aucune")

    def _on_manage_quantities(self, event):
        if not self.project: return
        dlg = QuantityManagerDialog(self, self.project.sale_quantities)
        if dlg.ShowModal() == wx.ID_OK:
            self.project.sale_quantities = dlg.get_quantities()
            self._update_qty_ui()
            if self.on_quantities_changed:
                self.on_quantities_changed(self.project.sale_quantities)
        dlg.Destroy()

    def get_quantities(self):
        return sorted(self.quantities)
