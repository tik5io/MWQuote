# ui/panels/operation_cost_editor_panel.py
import wx
import copy
from datetime import datetime
import domain.cost as domain_cost
from domain.operation import Operation, SUBCONTRACTING_TYPOLOGY, TOOLING_TYPOLOGY
from ui.components.result_summary_panel import ResultSummaryPanel
from ui.components.cost_item_editor import CostItemEditor
from ui.components.offers_comparison_grid import OffersComparisonGrid
from infrastructure.configuration import ConfigurationService
from infrastructure.logging_service import get_module_logger
from infrastructure.template_manager import TemplateManager

logger = get_module_logger("OperationCostEditor", "operation_cost_editor.log")

class OperationCostEditorPanel(wx.Panel):
    """Panel pour éditer les opérations du projet et leurs coûts associés."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.on_operation_updated = None
        self.current_data = None
        self.config_service = ConfigurationService()
        self.template_manager = None
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left side: Tree
        left_panel = wx.Panel(self)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        self.tree = wx.TreeCtrl(left_panel, style=wx.TR_HAS_BUTTONS | wx.TR_EDIT_LABELS)
        self.root = self.tree.AddRoot("Projet")
        left_sizer.Add(self.tree, 1, wx.EXPAND | wx.ALL, 5)

        tree_toolbar = wx.BoxSizer(wx.HORIZONTAL)
        add_op_btn = wx.Button(left_panel, label="+ Op", size=(40, -1))
        add_op_btn.Bind(wx.EVT_BUTTON, self._on_add_operation)
        tree_toolbar.Add(add_op_btn, 0, wx.ALL, 2)

        tpl_new_btn = wx.Button(left_panel, label="Depuis template", size=(110, -1))
        tpl_new_btn.Bind(wx.EVT_BUTTON, self._on_create_from_template)
        tree_toolbar.Add(tpl_new_btn, 0, wx.ALL, 2)

        add_cost_btn = wx.Button(left_panel, label="+ Coût", size=(50, -1))
        add_cost_btn.Bind(wx.EVT_BUTTON, self._on_add_cost_to_selected_op)
        tree_toolbar.Add(add_cost_btn, 0, wx.ALL, 2)

        del_btn = wx.Button(left_panel, label="X", size=(30, -1))
        del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        tree_toolbar.Add(del_btn, 0, wx.ALL, 2)

        up_btn = wx.Button(left_panel, label="↑", size=(30, -1))
        up_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_move_op(-1))
        tree_toolbar.Add(up_btn, 0, wx.ALL, 2)

        down_btn = wx.Button(left_panel, label="↓", size=(30, -1))
        down_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_move_op(1))
        tree_toolbar.Add(down_btn, 0, wx.ALL, 2)

        left_sizer.Add(tree_toolbar, 0, wx.EXPAND)
        left_panel.SetSizer(left_sizer)

        # Right side: Detail Panel
        self.properties_panel = wx.ScrolledWindow(self, style=wx.VSCROLL)
        self.properties_panel.SetScrollRate(0, 20)
        self.properties_content = wx.BoxSizer(wx.VERTICAL)
        
        # 1. Operation specific properties
        self.op_props_panel = wx.Panel(self.properties_panel)
        self.op_props_sizer = wx.BoxSizer(wx.VERTICAL) # Changed to self.op_props_sizer
        grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self.op_props_panel, label="Typologie:"))
        self.prop_op_typology = wx.Choice(self.op_props_panel, choices=self.config_service.get_cost_typologies())
        grid.Add(self.prop_op_typology, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self.op_props_panel, label="Libellé:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.prop_op_label = wx.TextCtrl(self.op_props_panel)
        grid.Add(self.prop_op_label, 1, wx.EXPAND)
        
        grid.Add(wx.StaticText(self.op_props_panel, label="Commentaire Chiffrage:"), 0, wx.TOP, 5)
        self.prop_op_comment = wx.TextCtrl(self.op_props_panel, style=wx.TE_MULTILINE, size=(-1, 100))
        grid.Add(self.prop_op_comment, 1, wx.EXPAND)

        self.template_status = wx.StaticText(self.op_props_panel, label="")
        self.template_status.SetForegroundColour(wx.Colour(170, 90, 0))
        self.op_props_sizer.Add(self.template_status, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        tpl_actions = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_save_template = wx.Button(self.op_props_panel, label="Enregistrer comme template")
        self.btn_save_template.Bind(wx.EVT_BUTTON, self._on_save_operation_as_template)
        tpl_actions.Add(self.btn_save_template, 0, wx.RIGHT, 8)
        self.btn_refresh_drift = wx.Button(self.op_props_panel, label="Recalcul drift")
        self.btn_refresh_drift.Bind(wx.EVT_BUTTON, self._on_recalc_template_drift)
        tpl_actions.Add(self.btn_refresh_drift, 0)
        self.op_props_sizer.Add(tpl_actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.op_props_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10) # Changed to self.op_props_sizer
        
        # Summary
        self.result_panel = ResultSummaryPanel(self.op_props_panel)
        self.op_props_sizer.Add(self.result_panel, 0, wx.EXPAND | wx.ALL, 5)
        # Comparison Grid
        self.comparison_grid = OffersComparisonGrid(self.op_props_panel)
        self.comparison_grid.Hide()
        self.op_props_sizer.Add(self.comparison_grid, 1, wx.EXPAND | wx.ALL, 5)
        
        self.op_props_panel.SetSizer(self.op_props_sizer) # Changed to self.op_props_sizer
        self.properties_content.Add(self.op_props_panel, 1, wx.EXPAND) # Proportions 1
        self.op_props_panel.Hide()

        # 2. Cost specific properties (Typology, Pricing, etc)
        self.cost_editor = CostItemEditor(self.properties_panel)
        self.cost_editor.on_changed = self._on_cost_changed
        self.properties_content.Add(self.cost_editor, 1, wx.EXPAND) # Proportions 1
        self.cost_editor.Hide()

        # 3. Results feedback (Always at the bottom) - This is now part of op_props_panel
        # self.result_panel = ResultSummaryPanel(self.properties_panel)
        # self.properties_content.Add(self.result_panel, 0, wx.EXPAND | wx.ALL, 10)
        # self.result_panel.Hide()

        self.properties_placeholder = wx.StaticText(self.properties_panel, label="Sélectionnez un élément")
        self.properties_content.Add(self.properties_placeholder, 0, wx.ALL, 20)

        # Les changements sont maintenant appliqués "à la volée" (On-the-fly)
        # On ne crée plus de bouton de sauvegarde globale.

        self.properties_panel.SetSizer(self.properties_content)

        main_sizer.Add(left_panel, 1, wx.EXPAND)
        main_sizer.Add(self.properties_panel, 2, wx.EXPAND)
        self.SetSizer(main_sizer)

        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_selection_changed)
        self.tree.Bind(wx.EVT_TREE_END_LABEL_EDIT, self._on_tree_end_label_edit)
        self.tree.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self._on_tree_right_click)

        # Bind events for the Operation properties
        self.prop_op_typology.Bind(wx.EVT_CHOICE, self._on_op_field_changed)
        self.prop_op_label.Bind(wx.EVT_TEXT, self._on_op_field_changed)
        self.prop_op_comment.Bind(wx.EVT_TEXT, self._on_op_field_changed)
        self.prop_op_label.Bind(wx.EVT_TEXT, self._on_op_field_changed)
        self.prop_op_comment.Bind(wx.EVT_TEXT, self._on_op_field_changed)

    def load_project(self, project):
        self.project = project
        logger.info(f"load_project | ops={len(project.operations) if project else 0}")
        if self.project:
            for op in self.project.operations:
                self._enforce_operation_constraints(op)
        self._refresh_tree()

    def set_database(self, db):
        self.template_manager = TemplateManager(db)

    def refresh_data(self):
        """Rafraîchit l'affichage sans recharger l'arbre (pour cohérence avec les autres panels)."""
        # Rafraîchir le panel de résultats si visible
        if self.result_panel.IsShown() and self.current_data:
            if self.current_data["type"] == "operation":
                self.result_panel.load_item(self.current_data["operation"], self.project)
        # Rafraîchir l'éditeur de coût si visible
        if self.cost_editor.IsShown() and self.current_data:
            if self.current_data["type"] == "cost":
                self.cost_editor.result_panel._refresh_qty_choice()
        # Rafraîchir la grille de comparaison si visible
        if self.comparison_grid.IsShown() and self.current_data:
            if self.current_data["type"] == "operation":
                self.comparison_grid.load_operation(self.current_data["operation"], self.project)

    def refresh_quantities(self):
        """Rafraîchit les sélecteurs de quantités dans les sous-composants."""
        if self.result_panel.IsShown():
            self.result_panel._refresh_qty_choice()
        if self.cost_editor.IsShown():
            self.cost_editor.result_panel._refresh_qty_choice()

    def update_root_label(self):
        """Update only the root item label based on the current project reference."""
        if self.project and self.root and self.root.IsOk():
            ref = self.project.reference if self.project.reference else "Projet"
            self.tree.SetItemText(self.root, ref)

    def _refresh_tree(self):
        self.tree.DeleteAllItems()
        ref = self.project.reference if self.project and self.project.reference else "Projet"
        self.root = self.tree.AddRoot(ref)
        if not self.project: return
        for op in self.project.operations:
            self._add_operation_to_tree(op, self.root)
        self.tree.ExpandAll()

    def _add_operation_to_tree(self, op, parent):
        if not parent or not parent.IsOk(): return None
        item = self.tree.AppendItem(parent, f"🔧 {op.typology or 'Op'} | {op.label}")
        self.tree.SetItemData(item, {"type": "operation", "operation": op})
        for cost_name, cost in op.costs.items():
            self._add_cost_to_tree(cost, item, op, cost_name)
        return item

    def _add_cost_to_tree(self, cost, parent, op, cost_key=None):
        if not parent or not parent.IsOk(): return None
        cost_icon = "💰" if cost.cost_type in [domain_cost.CostType.MATERIAL, domain_cost.CostType.SUBCONTRACTING] else "⚙️" if cost.cost_type == domain_cost.CostType.INTERNAL_OPERATION else "🛠️" if cost.cost_type == domain_cost.CostType.TOOLING else "📈"
        label = f"{cost_icon} {cost.name}"
        # from domain.operation import SUBCONTRACTING_TYPOLOGY # Already imported at top
        if op.typology == SUBCONTRACTING_TYPOLOGY and not cost.is_active:
            label = f"📁 [ARCHIVE] {cost.name}"
            
        item = self.tree.AppendItem(parent, label)
        if op.typology == SUBCONTRACTING_TYPOLOGY and not cost.is_active:
            self.tree.SetItemTextColour(item, wx.Colour(150, 150, 150))
            
        self.tree.SetItemData(item, {"type": "cost", "cost": cost, "operation": op, "cost_key": cost_key or cost.name})
        return item

    def _refresh_operation_items(self, op):
        """Update only the hierarchy of a single operation in the tree."""
        op_item = self._find_item_by_op(op, self.root)
        if not op_item or not op_item.IsOk():
            return
            
        # 1. Update Op label
        self.tree.SetItemText(op_item, f"🔧 {op.typology or 'Op'} | {op.label}")
        
        # 2. Update Costs (labels/colors/icons)
        child, cookie = self.tree.GetFirstChild(op_item)
        while child.IsOk():
            data = self.tree.GetItemData(child)
            if data and data["type"] == "cost":
                cost = data["cost"]
                
                icons = {
                    domain_cost.CostType.MATERIAL: "💰",
                    domain_cost.CostType.SUBCONTRACTING: "💰",
                    domain_cost.CostType.INTERNAL_OPERATION: "⚙️",
                    domain_cost.CostType.TOOLING: "🛠️"
                }
                cost_icon = icons.get(cost.cost_type, "📈")
                label = f"{cost_icon} {cost.name}"
                # from domain.operation import SUBCONTRACTING_TYPOLOGY # Already imported at top
                if op.typology == SUBCONTRACTING_TYPOLOGY and not cost.is_active:
                    label = f"📁 [ARCHIVE] {cost.name}"
                    self.tree.SetItemTextColour(child, wx.Colour(150, 150, 150))
                else:
                    self.tree.SetItemTextColour(child, wx.BLACK)
                self.tree.SetItemText(child, label)
            
            child, cookie = self.tree.GetNextChild(op_item, cookie)

    def _on_selection_changed(self, event):
        item = event.GetItem()
        if not item.IsOk() or item == self.root:
            self._clear_properties()
            return
        data = self.tree.GetItemData(item)
        self.current_data = data
        self._show_properties(data)

    def _clear_properties(self):
        self.current_data = None
        self.cost_editor.Hide()
        self.op_props_panel.Hide()
        self.properties_placeholder.Show()
        self.properties_panel.Layout()

    def _show_properties(self, data):
        self.properties_placeholder.Hide()
        
        if data["type"] == "operation":
            self.cost_editor.Hide()
            self.op_props_panel.Show()
            op = data["operation"]
            
            if op.typology == SUBCONTRACTING_TYPOLOGY:
                self.result_panel.Hide()
                self.comparison_grid.Show()
                self.comparison_grid.load_operation(op, self.project)
            else:
                self.comparison_grid.Hide()
                self.result_panel.Show()
                self.result_panel.load_item(op, self.project)
                
            # Freeze to avoid flickers during value setting
            self.op_props_panel.Freeze()
            if op.typology:
                self.prop_op_typology.SetStringSelection(op.typology)
            else:
                self.prop_op_typology.SetSelection(0)
            self.prop_op_label.ChangeValue(op.label or "")
            self.prop_op_comment.ChangeValue(op.comment or "")
            self.op_props_panel.Thaw() # Restore Thaw
            
            self.result_panel.Show()
            self.result_panel.load_item(op, self.project)
            self._update_template_flag(op)
        else:
            self.op_props_panel.Hide()
            self.result_panel.Hide() # Hide parent's result panel for costs
            self.cost_editor.Show()
            self.cost_editor.load_cost(data["cost"], self.project)
        
        # Ensure sizer and panel are correctly recalculated to avoid overlaps
        self.properties_content.Layout()
        self.properties_panel.Layout()

    def _on_cost_changed(self, temp_cost):
        """Callback from CostItemEditor when any field changes (real-time)."""
        data = self.current_data
        if not data or data["type"] != "cost":
            return
            
        cost = data["cost"]
        op = data["operation"]
        logger.debug(f"on_cost_changed | op={op.code if op else '?'} cost={getattr(cost, 'name', '?')}")

        if self._is_tooling_operation(op):
            self._enforce_tooling_cost_shape(cost, op)
            if self.cost_editor.prop_name.GetValue().strip() != "Outillage":
                self.cost_editor.prop_name.ChangeValue("Outillage")
        
        # 1. Handle Renaming safely
        current_key = self._resolve_cost_key(op, cost, data.get("cost_key", cost.name))
        data["cost_key"] = current_key
        new_name = self.cost_editor.prop_name.GetValue().strip()
        if new_name and new_name != current_key:
            # We must use the domain's rename logic to update the dictionary key
            if not op.rename_cost(current_key, new_name):
                # Revert UI if rename is invalid to avoid desync
                logger.warning(f"rename_cost rejected | old={current_key} new={new_name}")
                self.cost_editor.prop_name.ChangeValue(current_key)
            else:
                data["cost_key"] = new_name
            
        # ALWAYS update tree label to match current state (handles typing)
        if self.cost_editor.apply_changes():
            data["cost_key"] = cost.name
            if self.template_manager and getattr(op, "template_id", None):
                op.template_drift_score = self.template_manager.compute_drift_score(op)
                self._update_template_flag(op)
            # 2.1 Exclusive activation for Subcontracting
            from domain.operation import SUBCONTRACTING_TYPOLOGY
            if op.typology == SUBCONTRACTING_TYPOLOGY and cost.cost_type == domain_cost.CostType.SUBCONTRACTING and cost.is_active:
                for other_cost in op.costs.values():
                    if other_cost != cost and other_cost.cost_type == domain_cost.CostType.SUBCONTRACTING:
                        other_cost.is_active = False
                
                # Optimized: update only current operation subtree
                self._refresh_operation_items(op)
            else:
                # Update only current label to match current state (handles typing)
                item = self.tree.GetSelection()
                if item and item.IsOk():
                    icons = {
                        domain_cost.CostType.MATERIAL: "💰",
                        domain_cost.CostType.SUBCONTRACTING: "💰",
                        domain_cost.CostType.INTERNAL_OPERATION: "⚙️",
                        domain_cost.CostType.TOOLING: "🛠️"
                    }
                    cost_icon = icons.get(cost.cost_type, "📈")
                    label = f"{cost_icon} {cost.name}"
                    if op.typology == SUBCONTRACTING_TYPOLOGY and not cost.is_active:
                        label = f"📁 [ARCHIVE] {cost.name}"
                        self.tree.SetItemTextColour(item, wx.Colour(150, 150, 150))
                    else:
                        self.tree.SetItemTextColour(item, wx.BLACK)
                    self.tree.SetItemText(item, label)

            # 4. Notify main frame to refresh other panels (totals, graphs, sales grid)
            if self.on_operation_updated:
                self.on_operation_updated(None) # None means project header is NOT reloaded (performance)
        else:
            logger.warning("apply_changes returned False")

    def _on_op_field_changed(self, event):
        """Handle real-time updates for Operation fields."""
        data = self.current_data
        if not data or data["type"] != "operation":
            return
            
        op = data["operation"]
        logger.debug(f"on_op_field_changed | op={op.code if op else '?'}")
        before_state = [(k, v.cost_type.value, v.name) for k, v in op.costs.items()]
        op.typology = self.prop_op_typology.GetStringSelection()
        op.code = op.typology # Match legacy typology/code link
        op.label = self.prop_op_label.GetValue().strip()
        op.comment = self.prop_op_comment.GetValue()
        self._enforce_operation_constraints(op)
        if self.template_manager and getattr(op, "template_id", None):
            op.template_drift_score = self.template_manager.compute_drift_score(op)
        after_state = [(k, v.cost_type.value, v.name) for k, v in op.costs.items()]
        
        # Update Tree Label
        item = self.tree.GetSelection()
        if item.IsOk():
            self.tree.SetItemText(item, f"🔧 {op.typology or 'Op'} | {op.label}")
            if before_state != after_state:
                self._refresh_tree()
                new_item = self._find_item_by_op(op, self.root)
                if new_item:
                    self.tree.SelectItem(new_item)
            
        # Update preview
        self.result_panel.update_results(op)
        self._update_template_flag(op)
        
        # Notify main frame
        if self.on_operation_updated:
            self.on_operation_updated(None)

    def _on_add_operation(self, event):
        op = Operation(code="NOUV", label="Nouvelle")
        self.project.add_operation(op)
        self._refresh_tree()
        if self.on_operation_updated:
            self.on_operation_updated(op, reload_header=True)

    def _on_create_from_template(self, event):
        if not self.project:
            return
        if not self.template_manager:
            wx.MessageBox("TemplateManager indisponible.", "Erreur", wx.OK | wx.ICON_ERROR)
            return
        templates = self.template_manager.list_templates()
        if not templates:
            wx.MessageBox("Aucun template disponible.", "Templates", wx.OK | wx.ICON_INFORMATION)
            return
        labels = [f"[{t['typology']}] {t['name']} (#{t['id']})" for t in templates]
        dlg = wx.SingleChoiceDialog(self, "Sélectionner un template", "Créer depuis template", labels)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        idx = dlg.GetSelection()
        dlg.Destroy()
        tpl = templates[idx]
        op = self.template_manager.build_operation_from_template(tpl)
        if not op.label or op.label == tpl.get("name"):
            op.label = f"{tpl.get('name')} - copie"
        self.project.add_operation(op)
        self._refresh_tree()
        if self.root and self.root.IsOk():
            op_item = self._find_item_by_op(op, self.root)
            if op_item:
                self.tree.SelectItem(op_item)
        if self.on_operation_updated:
            self.on_operation_updated(op, reload_header=True)

    def _on_save_operation_as_template(self, event):
        data = self.current_data
        if not data or data.get("type") != "operation":
            wx.MessageBox("Sélectionnez une opération d'abord.", "Template", wx.OK | wx.ICON_INFORMATION)
            return
        if not self.template_manager:
            wx.MessageBox("TemplateManager indisponible.", "Erreur", wx.OK | wx.ICON_ERROR)
            return
        op = data["operation"]
        default_name = f"{op.typology or 'Template'} - {op.label or 'Operation'}"
        dlg = wx.TextEntryDialog(self, "Nom du template :", "Enregistrer comme template", default_name)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        name = dlg.GetValue().strip()
        dlg.Destroy()
        if not name:
            return
        tid = self.template_manager.save_template_from_operation(op, name)
        op.template_id = tid
        op.template_name = name
        op.template_snapshot = self.template_manager._operation_to_template_payload(op)
        op.template_drift_score = 0.0
        self._update_template_flag(op)
        if self.on_operation_updated:
            self.on_operation_updated(op)
        wx.MessageBox(f"Template enregistré (ID {tid}).", "Template", wx.OK | wx.ICON_INFORMATION)

    def _on_recalc_template_drift(self, event):
        data = self.current_data
        if not data or data.get("type") != "operation":
            return
        op = data["operation"]
        if self.template_manager and getattr(op, "template_snapshot", None):
            op.template_drift_score = self.template_manager.compute_drift_score(op)
            self._update_template_flag(op)
            if self.on_operation_updated:
                self.on_operation_updated(op)

    def _update_template_flag(self, op):
        if not hasattr(self, "template_status"):
            return
        if not getattr(op, "template_id", None):
            self.template_status.SetLabel("Template: aucun")
            self.template_status.SetForegroundColour(wx.Colour(120, 120, 120))
            return
        drift = float(getattr(op, "template_drift_score", 0.0) or 0.0)
        self.template_status.SetLabel(
            f"Template #{op.template_id} - {op.template_name or '-'} | Drift: {drift:.1f}%"
        )
        if drift >= 30:
            self.template_status.SetForegroundColour(wx.Colour(190, 60, 40))
        elif drift > 0:
            self.template_status.SetForegroundColour(wx.Colour(170, 110, 0))
        else:
            self.template_status.SetForegroundColour(wx.Colour(40, 120, 40))

    def _on_add_cost_to_selected_op(self, event):
        item = self.tree.GetSelection()
        if not item.IsOk(): return
        data = self.tree.GetItemData(item)
        op = data["operation"] if data else None
        if not op: return

        if self._is_tooling_operation(op) and len(op.costs) >= 1:
            wx.MessageBox(
                "L'opération OUTILLAGE n'accepte qu'un seul coût nommé 'Outillage'.",
                "Règle OUTILLAGE",
                wx.OK | wx.ICON_INFORMATION
            )
            if op.costs:
                tooling_cost = next(iter(op.costs.values()))
                op_item = self._find_item_by_op(op, self.root) if self.root and self.root.IsOk() else None
                if op_item:
                    existing_item = self._find_item_by_cost(tooling_cost, op_item)
                    if existing_item:
                        self.tree.SelectItem(existing_item)
            return
        
        # Generate unique name
        base_name = "Nouveau coût"
        name = base_name
        counter = 1
        while name in op.costs:
            name = f"{base_name} {counter}"
            counter += 1

        ct = domain_cost.CostType.TOOLING if self._is_tooling_operation(op) else domain_cost.CostType.INTERNAL_OPERATION
        pricing = domain_cost.PricingStructure(domain_cost.PricingType.PER_UNIT)
        cost = domain_cost.CostItem(name, ct, pricing)
        if self._is_tooling_operation(op):
            cost.name = "Outillage"
            name = "Outillage"
        op.costs[name] = cost
        
        self._refresh_tree()
        # After refresh_tree, the 'item' handle is invalid. Must re-find.
        if self.root and self.root.IsOk():
            op_item = self._find_item_by_op(op, self.root)
            if op_item and op_item.IsOk():
                new_item = self._find_item_by_cost(cost, op_item)
                if new_item and new_item.IsOk():
                    self.tree.SelectItem(new_item)
            
        if self.on_operation_updated:
            self.on_operation_updated(op, reload_header=True)

    def _on_delete(self, event):
        item = self.tree.GetSelection()
        if not item.IsOk() or item == self.root: return
        data = self.tree.GetItemData(item)
        if wx.MessageBox("Confirmer ?", "Supprimer", wx.YES_NO) != wx.YES: return
        try:
            if data["type"] == "operation": 
                self.project.operations.remove(data["operation"])
            else: 
                op = data["operation"]
                cost = data["cost"]
                if self._is_tooling_operation(op) and len(op.costs) <= 1:
                    wx.MessageBox(
                        "L'opération OUTILLAGE doit conserver son coût unique 'Outillage'.",
                        "Règle OUTILLAGE",
                        wx.OK | wx.ICON_INFORMATION
                    )
                    return
                cost_key = data.get("cost_key", cost.name)
                if cost_key in op.costs:
                    del op.costs[cost_key]
                else:
                    # Fallback if names are out of sync
                    found = False
                    for k, v in list(op.costs.items()):
                        if v == cost:
                            del op.costs[k]
                            found = True
                            break
                    if not found:
                        wx.MessageBox("Erreur : l'élément n'a pas pu être trouvé dans le dictionnaire des coûts.", "Erreur", wx.OK | wx.ICON_ERROR)
                        return
            self.tree.Delete(item)
            if self.on_operation_updated:
                self.on_operation_updated(None, reload_header=True)
        except Exception as e:
            wx.MessageBox(f"Une erreur est survenue lors de la suppression : {str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _on_tree_end_label_edit(self, event):
        if event.IsEditCancelled(): return
        item = event.GetItem()
        data = self.tree.GetItemData(item)
        new_label = event.GetLabel().strip()
        if not new_label:
            event.Veto()
            return

        if data["type"] == "operation": 
            data["operation"].label = new_label
        else: 
            op = data["operation"]
            cost = data["cost"]
            if self._is_tooling_operation(op) and new_label != "Outillage":
                event.Veto()
                wx.MessageBox("Le coût de l'opération OUTILLAGE doit rester nommé 'Outillage'.", "Règle OUTILLAGE")
                return
            current_key = self._resolve_cost_key(op, cost, data.get("cost_key", cost.name))
            if not op.rename_cost(current_key, new_label):
                event.Veto()
                wx.MessageBox("Nom déjà utilisé ou invalide.", "Erreur")
                return
            data["cost_key"] = new_label
        if self.on_operation_updated: self.on_operation_updated(None)

    def _on_tree_right_click(self, event):
        item = event.GetItem()
        if item.IsOk() and item != self.root:
            self.tree.SelectItem(item)
            data = self.tree.GetItemData(item)
            menu = wx.Menu()
            ren = menu.Append(wx.ID_ANY, "Renommer")
            self.Bind(wx.EVT_MENU, lambda e: self.tree.EditLabel(item), ren)
            del_item = menu.Append(wx.ID_ANY, "Supprimer")
            self.Bind(wx.EVT_MENU, self._on_delete, del_item)
            
            if data and data["type"] == "operation":
                menu.AppendSeparator()
                move_up = menu.Append(wx.ID_ANY, "Monter")
                self.Bind(wx.EVT_MENU, lambda e: self._on_move_op(-1), move_up)
                move_down = menu.Append(wx.ID_ANY, "Descendre")
                self.Bind(wx.EVT_MENU, lambda e: self._on_move_op(1), move_down)
            
            if data and data["type"] == "cost":
                menu.AppendSeparator()
                from domain.operation import SUBCONTRACTING_TYPOLOGY
                op = data["operation"]
                cost = data["cost"]

                calc_note = menu.Append(wx.ID_ANY, "Note de calcul tarifaire...")
                self.Bind(wx.EVT_MENU, lambda e: self._show_tariff_calculation_note(cost, op), calc_note)
                menu.AppendSeparator()

                if op.typology == SUBCONTRACTING_TYPOLOGY and cost.cost_type == domain_cost.CostType.SUBCONTRACTING:
                    act = menu.Append(wx.ID_ANY, "Définir comme offre active")
                    self.Bind(wx.EVT_MENU, lambda e: self._on_activate_cost(cost, op), act)
                    menu.AppendSeparator()
                    
                move_up = menu.Append(wx.ID_ANY, "Monter")
                self.Bind(wx.EVT_MENU, lambda e: self._on_move_op(-1), move_up)
                move_down = menu.Append(wx.ID_ANY, "Descendre")
                self.Bind(wx.EVT_MENU, lambda e: self._on_move_op(1), move_down)
                
            self.PopupMenu(menu)
            menu.Destroy()
    
    def _show_tariff_calculation_note(self, cost, op):
        """Show a detailed calculation note for the selected cost item."""
        note_text = self._build_tariff_calculation_note(cost, op)

        dlg = wx.Dialog(self, title="Note de calcul tarifaire", size=(900, 700))
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        txt = wx.TextCtrl(
            dlg,
            value=note_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL
        )
        main_sizer.Add(txt, 1, wx.EXPAND | wx.ALL, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        copy_btn = wx.Button(dlg, label="Copier")
        close_btn = wx.Button(dlg, wx.ID_OK, "Fermer")
        btn_sizer.Add(copy_btn, 0, wx.RIGHT, 8)
        btn_sizer.Add(close_btn, 0)
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        def on_copy(_):
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(note_text))
                wx.TheClipboard.Close()
                wx.MessageBox("Note copiée dans le presse-papiers.", "Information", wx.OK | wx.ICON_INFORMATION)

        copy_btn.Bind(wx.EVT_BUTTON, on_copy)
        dlg.SetSizer(main_sizer)
        dlg.ShowModal()
        dlg.Destroy()

    def _build_tariff_calculation_note(self, cost, op):
        from domain.calculator import Calculator

        def euros(value):
            return f"{value:.4f} EUR"

        def number(value):
            return f"{value:.4f}"

        quantities = []
        if self.project and getattr(self.project, "sale_quantities", None):
            quantities = sorted([q for q in self.project.sale_quantities if q and q > 0])
        if not quantities:
            quantities = [1]

        unit_label = cost.pricing.unit if cost.pricing and cost.pricing.unit else "unite"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = []
        lines.append("NOTE DE CALCUL TARIFAIRE")
        lines.append("")
        lines.append(f"Date generation: {now_str}")
        lines.append(f"Projet: {self.project.reference if self.project else '-'} | {self.project.name if self.project else '-'}")
        lines.append(f"Operation: {op.typology or '-'} | {op.label}")
        lines.append(f"Poste de cout: {cost.name}")
        lines.append(f"Type de cout: {cost.cost_type.value}")
        lines.append(f"Conversion: {cost.conversion_type.value} x facteur {number(cost.conversion_factor if cost.conversion_factor else 1.0)}")
        lines.append(f"Marge appliquee: {number(cost.margin_rate)} %")
        lines.append("")

        if cost.cost_type == domain_cost.CostType.INTERNAL_OPERATION:
            lines.append("Parametres operation interne")
            lines.append(f"- Taux horaire: {euros(cost.hourly_rate)} / h")
            lines.append(f"- Temps fixe: {number(cost.fixed_time)} h")
            lines.append(f"- Temps par piece: {number(cost.per_piece_time)} h/pc")
            lines.append("")
        else:
            ptype = cost.pricing.pricing_type.value if cost.pricing else "-"
            lines.append("Parametres achat/fournisseur")
            lines.append(f"- Unite de devis: {unit_label}")
            lines.append(f"- Type tarif fournisseur: {ptype}")
            if cost.pricing:
                lines.append(f"- Frais fixes fournisseur: {euros(cost.pricing.fixed_price)}")
                lines.append(f"- Prix unitaire fournisseur: {euros(cost.pricing.unit_price)} / {unit_label}")
                if cost.pricing.pricing_type == domain_cost.PricingType.TIERED and cost.pricing.tiers:
                    lines.append("- Echelons:")
                    for tier in sorted(cost.pricing.tiers, key=lambda t: t.min_quantity):
                        lines.append(f"  * Q >= {tier.min_quantity}: {euros(tier.unit_price)} / {unit_label}")
            lines.append("")

        for qty in quantities:
            res = Calculator.calculate_item(cost, qty)
            lines.append("=" * 72)
            lines.append(f"QUANTITE DE VENTE: {qty} pc")
            lines.append("Etape 1 - Quantite de devis necessaire")
            if cost.quantity_per_piece_is_inverse:
                val = cost.quantity_per_piece if cost.quantity_per_piece not in (None, 0) else 1.0
                lines.append(f"- Mode inverse (pieces/{unit_label}) = {number(val)}")
                lines.append(f"- Q devis necessaire = ceil({qty} / {number(val)}) = {number(res.quote_qty_needed)} {unit_label}")
            else:
                val = cost.quantity_per_piece if cost.quantity_per_piece is not None else 1.0
                lines.append(f"- Consommation ({unit_label}/piece) = {number(val)}")
                lines.append(f"- Q devis necessaire = {qty} x {number(val)} = {number(res.quote_qty_needed)} {unit_label}")

            lines.append("Etape 2 - Application MOQ / quantite commandee")
            lines.append(f"- MOQ = {number(res.moq)} {unit_label}")
            lines.append(f"- Q commandee = max(Q necessaire, MOQ) = {number(res.quote_qty_ordered)} {unit_label}")

            lines.append("Etape 3 - Cout lot fournisseur")
            if cost.cost_type == domain_cost.CostType.INTERNAL_OPERATION:
                total_time = cost.fixed_time + (cost.per_piece_time * qty)
                lines.append(f"- Temps total = {number(cost.fixed_time)} + ({number(cost.per_piece_time)} x {qty}) = {number(total_time)} h")
                lines.append(f"- Cout lot = Temps total x taux horaire = {number(total_time)} x {euros(cost.hourly_rate)} = {euros(res.batch_supplier_cost)}")
            else:
                if cost.pricing and cost.pricing.pricing_type == domain_cost.PricingType.TIERED and cost.pricing.tiers:
                    tier = cost.pricing.get_applicable_tier(res.quote_qty_ordered)
                    if tier:
                        lines.append(f"- Echelon applique: Q >= {tier.min_quantity}, PU = {euros(tier.unit_price)} / {unit_label}")
                    else:
                        lines.append("- Echelon applique: aucun (repli sur plus proche)")
                lines.append(f"- Cout lot fournisseur = {euros(res.batch_supplier_cost)}")
                lines.append(f"  dont fixe = {euros(res.supplier_fixed_price)}")
                variable = res.batch_supplier_cost - res.supplier_fixed_price
                lines.append(f"  dont variable = {euros(variable)}")

            lines.append("Etape 4 - Cout unitaire brut")
            lines.append(f"- Cout unitaire brut = Cout lot / quantite vente = {euros(res.batch_supplier_cost)} / {qty} = {euros(res.unit_cost_brut)} /pc")

            lines.append("Etape 5 - Conversion")
            factor = res.conversion_factor if res.conversion_factor else 1.0
            if res.conversion_type == domain_cost.ConversionType.DIVIDE:
                lines.append(f"- Cout unitaire converti = {euros(res.unit_cost_brut)} / {number(factor)} = {euros(res.unit_cost_converted)} /pc")
            else:
                lines.append(f"- Cout unitaire converti = {euros(res.unit_cost_brut)} x {number(factor)} = {euros(res.unit_cost_converted)} /pc")

            lines.append("Etape 6 - Application marge (prix de vente)")
            margin = min(cost.margin_rate, 99.9)
            margin_factor = 1.0 / (1.0 - margin / 100.0)
            lines.append(f"- Coef marge = 1 / (1 - {number(margin)} / 100) = {number(margin_factor)}")
            lines.append(f"- Prix de vente unitaire = {euros(res.unit_cost_converted)} x {number(margin_factor)} = {euros(res.unit_sale_price)} /pc")
            lines.append(f"- Prix de vente lot ({qty} pc) = {euros(res.unit_sale_price * qty)}")
            lines.append("")

        lines.append("Conclusion")
        lines.append("- Cette note detaille les calculs intermediaires pour verification et revue de chiffrage.")
        return "\n".join(lines)

    def _on_activate_cost(self, cost, op):
        """Manually activate a cost via right-click."""
        if cost.cost_type != domain_cost.CostType.SUBCONTRACTING:
            return
        cost.is_active = True
        for other_cost in op.costs.values():
            if other_cost != cost and other_cost.cost_type == domain_cost.CostType.SUBCONTRACTING:
                other_cost.is_active = False
        
        self._refresh_operation_items(op)
        # Also refresh property editor if it was showing this cost
        if self.current_data and self.current_data.get("cost") == cost:
            self.cost_editor.load_cost(cost, self.project)
            
        if self.on_operation_updated:
            self.on_operation_updated(None)

    def _on_move_op(self, direction):
        item = self.tree.GetSelection()
        if not item.IsOk(): return
        data = self.tree.GetItemData(item)
        if not data: return
        
        if data["type"] == "operation":
            op = data["operation"]
            try:
                idx = self.project.operations.index(op)
                if self.project.move_operation(idx, direction):
                    self._refresh_tree()
                    new_item = self._find_item_by_op(op, self.root)
                    if new_item: self.tree.SelectItem(new_item)
                    if self.on_operation_updated: self.on_operation_updated(None)
            except ValueError: pass
        elif data["type"] == "cost":
            op = data["operation"]
            cost = data["cost"]
            cost_key = data.get("cost_key", cost.name)
            if op.move_cost(cost_key, direction):
                self._refresh_tree()
                # Find the parent op item first, then find the cost item under it
                op_item = self._find_item_by_op(op, self.root)
                if op_item:
                    new_cost_item = self._find_item_by_cost(cost, op_item)
                    if new_cost_item:
                        self.tree.SelectItem(new_cost_item)
                if self.on_operation_updated: self.on_operation_updated(op)

    def _find_item_by_op(self, op, root_item):
        if not root_item or not root_item.IsOk(): return None
        child, cookie = self.tree.GetFirstChild(root_item)
        while child.IsOk():
            data = self.tree.GetItemData(child)
            if data and data.get("operation") == op and data["type"] == "operation":
                return child
            child, cookie = self.tree.GetNextChild(root_item, cookie)
        return None

    def _find_item_by_cost(self, cost, op_item):
        if not op_item or not op_item.IsOk(): return None
        child, cookie = self.tree.GetFirstChild(op_item)
        while child.IsOk():
            data = self.tree.GetItemData(child)
            if data and data.get("cost") == cost:
                return child
            child, cookie = self.tree.GetNextChild(op_item, cookie)
        return None

    def _resolve_cost_key(self, op, cost, fallback_key):
        """Resolve the real dict key for a cost object to avoid key desync issues."""
        if fallback_key in op.costs and op.costs.get(fallback_key) is cost:
            return fallback_key
        if cost.name in op.costs and op.costs.get(cost.name) is cost:
            return cost.name
        for key, value in op.costs.items():
            if value is cost:
                return key
        return fallback_key

    def _is_tooling_operation(self, op):
        return (op.typology or "").strip().upper() == TOOLING_TYPOLOGY

    def _enforce_tooling_cost_shape(self, cost, op):
        if cost.cost_type != domain_cost.CostType.TOOLING:
            cost.cost_type = domain_cost.CostType.TOOLING
        if not cost.pricing:
            cost.pricing = domain_cost.PricingStructure(domain_cost.PricingType.PER_UNIT)
        if cost.name != "Outillage":
            current_key = self._resolve_cost_key(op, cost, cost.name)
            if current_key != "Outillage":
                op.rename_cost(current_key, "Outillage")
            else:
                cost.name = "Outillage"

    def _enforce_operation_constraints(self, op):
        if not self._is_tooling_operation(op):
            return

        if not op.costs:
            pricing = domain_cost.PricingStructure(domain_cost.PricingType.PER_UNIT)
            op.costs["Outillage"] = domain_cost.CostItem("Outillage", domain_cost.CostType.TOOLING, pricing)
            return

        tooling_key = None
        for key, cost in op.costs.items():
            if cost.cost_type == domain_cost.CostType.TOOLING:
                tooling_key = key
                break
        if tooling_key is None:
            tooling_key = next(iter(op.costs.keys()))

        keep_cost = op.costs[tooling_key]
        self._enforce_tooling_cost_shape(keep_cost, op)

        op.costs = {"Outillage": keep_cost}
