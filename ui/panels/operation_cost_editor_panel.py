# ui/panels/operation_cost_editor_panel.py
import wx
import copy
import domain.cost as domain_cost
from domain.operation import Operation, SUBCONTRACTING_TYPOLOGY
from ui.components.result_summary_panel import ResultSummaryPanel
from ui.components.cost_item_editor import CostItemEditor
from ui.components.offers_comparison_grid import OffersComparisonGrid
from infrastructure.configuration import ConfigurationService

class OperationCostEditorPanel(wx.Panel):
    """Panel pour éditer les opérations du projet et leurs coûts associés."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.on_operation_updated = None
        self.current_data = None
        self.config_service = ConfigurationService()
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
        self._refresh_tree()

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
        for cost in op.costs.values():
            self._add_cost_to_tree(cost, item, op)
        return item

    def _add_cost_to_tree(self, cost, parent, op):
        if not parent or not parent.IsOk(): return None
        cost_icon = "💰" if cost.cost_type in [domain_cost.CostType.MATERIAL, domain_cost.CostType.SUBCONTRACTING] else "⚙️" if cost.cost_type == domain_cost.CostType.INTERNAL_OPERATION else "📈"
        label = f"{cost_icon} {cost.name}"
        # from domain.operation import SUBCONTRACTING_TYPOLOGY # Already imported at top
        if op.typology == SUBCONTRACTING_TYPOLOGY and not cost.is_active:
            label = f"📁 [ARCHIVE] {cost.name}"
            
        item = self.tree.AppendItem(parent, label)
        if op.typology == SUBCONTRACTING_TYPOLOGY and not cost.is_active:
            self.tree.SetItemTextColour(item, wx.Colour(150, 150, 150))
            
        self.tree.SetItemData(item, {"type": "cost", "cost": cost, "operation": op})
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
                    domain_cost.CostType.INTERNAL_OPERATION: "⚙️"
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
        
        # 1. Handle Renaming safely
        new_name = self.cost_editor.prop_name.GetValue().strip()
        if new_name and new_name != cost.name:
            # We must use the domain's rename logic to update the dictionary key
            op.rename_cost(cost.name, new_name)
            
        # ALWAYS update tree label to match current state (handles typing)
        if self.cost_editor.apply_changes():
            # 2.1 Exclusive activation for Subcontracting
            from domain.operation import SUBCONTRACTING_TYPOLOGY
            if op.typology == SUBCONTRACTING_TYPOLOGY and cost.is_active:
                for other_cost in op.costs.values():
                    if other_cost != cost:
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
                        domain_cost.CostType.INTERNAL_OPERATION: "⚙️"
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

    def _on_op_field_changed(self, event):
        """Handle real-time updates for Operation fields."""
        data = self.current_data
        if not data or data["type"] != "operation":
            return
            
        op = data["operation"]
        op.typology = self.prop_op_typology.GetStringSelection()
        op.code = op.typology # Match legacy typology/code link
        op.label = self.prop_op_label.GetValue().strip()
        op.comment = self.prop_op_comment.GetValue()
        
        # Update Tree Label
        item = self.tree.GetSelection()
        if item.IsOk():
            self.tree.SetItemText(item, f"🔧 {op.typology or 'Op'} | {op.label}")
            
        # Update preview
        self.result_panel.update_results(op)
        
        # Notify main frame
        if self.on_operation_updated:
            self.on_operation_updated(None)

    def _on_add_operation(self, event):
        op = Operation(code="NOUV", label="Nouvelle")
        self.project.add_operation(op)
        self._refresh_tree()
        if self.on_operation_updated: self.on_operation_updated(op)

    def _on_add_cost_to_selected_op(self, event):
        item = self.tree.GetSelection()
        if not item.IsOk(): return
        data = self.tree.GetItemData(item)
        op = data["operation"] if data else None
        if not op: return
        
        # Generate unique name
        base_name = "Nouveau coût"
        name = base_name
        counter = 1
        while name in op.costs:
            name = f"{base_name} {counter}"
            counter += 1

        ct = domain_cost.CostType.INTERNAL_OPERATION
        pricing = domain_cost.PricingStructure(domain_cost.PricingType.PER_UNIT)
        cost = domain_cost.CostItem(name, ct, pricing)
        op.costs[name] = cost
        
        self._refresh_tree()
        # After refresh_tree, the 'item' handle is invalid. Must re-find.
        if self.root and self.root.IsOk():
            op_item = self._find_item_by_op(op, self.root)
            if op_item and op_item.IsOk():
                new_item = self._find_item_by_cost(cost, op_item)
                if new_item and new_item.IsOk():
                    self.tree.SelectItem(new_item)
            
        if self.on_operation_updated: self.on_operation_updated(op)

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
                if cost.name in op.costs:
                    del op.costs[cost.name]
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
            if self.on_operation_updated: self.on_operation_updated(None)
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
            if not op.rename_cost(cost.name, new_label):
                event.Veto()
                wx.MessageBox("Nom déjà utilisé ou invalide.", "Erreur")
                return
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
                if op.typology == SUBCONTRACTING_TYPOLOGY:
                    act = menu.Append(wx.ID_ANY, "Définir comme offre active")
                    self.Bind(wx.EVT_MENU, lambda e: self._on_activate_cost(cost, op), act)
                    menu.AppendSeparator()
                    
                move_up = menu.Append(wx.ID_ANY, "Monter")
                self.Bind(wx.EVT_MENU, lambda e: self._on_move_op(-1), move_up)
                move_down = menu.Append(wx.ID_ANY, "Descendre")
                self.Bind(wx.EVT_MENU, lambda e: self._on_move_op(1), move_down)
                
            self.PopupMenu(menu)
            menu.Destroy()

    def _on_activate_cost(self, cost, op):
        """Manually activate a cost via right-click."""
        cost.is_active = True
        for other_cost in op.costs.values():
            if other_cost != cost:
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
            if op.move_cost(cost.name, direction):
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
