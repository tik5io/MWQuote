# ui/panels/operation_cost_editor_panel.py
import wx
import copy
from domain.cost import CostType, PricingType, PricingStructure, PricingTier, CostItem
from domain.operation import Operation

class OperationCostEditorPanel(wx.Panel):
    """Panel for editing project structure (operations and costs) in a tree view."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.on_operation_updated = None
        self.current_data = None
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Title
        self.title = wx.StaticText(self, label="Structure du projet")
        self.title.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        main_sizer.Add(self.title, 0, wx.ALL, 10)

        # Toolbar
        toolbar_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.add_op_btn = wx.Button(self, label="+ Opération")
        self.add_op_btn.SetToolTip("Ajouter une opération au projet")
        self.add_op_btn.Bind(wx.EVT_BUTTON, self._on_add_operation)
        toolbar_sizer.Add(self.add_op_btn, 0, wx.ALL, 2)

        self.add_cost_btn = wx.Button(self, label="+ Coût")
        self.add_cost_btn.SetToolTip("Ajouter un coût à l'élément sélectionné")
        self.add_cost_btn.Bind(wx.EVT_BUTTON, self._on_add_cost_to_selected_op)
        self.add_cost_btn.Disable()
        toolbar_sizer.Add(self.add_cost_btn, 0, wx.ALL, 2)

        toolbar_sizer.AddSpacer(10)

        self.delete_btn = wx.Button(self, label="Supprimer")
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        toolbar_sizer.Add(self.delete_btn, 0, wx.ALL, 2)

        self.duplicate_btn = wx.Button(self, label="Dupliquer")
        self.duplicate_btn.Bind(wx.EVT_BUTTON, self._on_duplicate)
        toolbar_sizer.Add(self.duplicate_btn, 0, wx.ALL, 2)

        toolbar_sizer.AddSpacer(10)

        self.move_up_btn = wx.Button(self, label="↑", size=(30, -1))
        self.move_up_btn.Bind(wx.EVT_BUTTON, self._on_move_up)
        toolbar_sizer.Add(self.move_up_btn, 0, wx.ALL, 2)

        self.move_down_btn = wx.Button(self, label="↓", size=(30, -1))
        self.move_down_btn.Bind(wx.EVT_BUTTON, self._on_move_down)
        toolbar_sizer.Add(self.move_down_btn, 0, wx.ALL, 2)

        toolbar_sizer.AddStretchSpacer()

        toolbar_sizer.Add(wx.StaticText(self, label="Qté projet:"), 0, wx.ALL | wx.ALIGN_CENTER, 5)
        self.pieces_ctrl = wx.SpinCtrl(self, min=1, max=1000000, initial=1)
        self.pieces_ctrl.Bind(wx.EVT_SPINCTRL, self._on_pieces_changed)
        toolbar_sizer.Add(self.pieces_ctrl, 0, wx.ALL, 5)

        main_sizer.Add(toolbar_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # Splitter for Tree and Properties
        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        
        # Tree control
        self.tree = wx.TreeCtrl(splitter, style=wx.TR_DEFAULT_STYLE | wx.TR_EDIT_LABELS)
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_tree_selection_changed)
        self.tree.Bind(wx.EVT_TREE_END_LABEL_EDIT, self._on_tree_end_label_edit)
        self.tree.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self._on_tree_right_click)

        # Properties panel
        self.properties_panel = self._create_properties_panel(splitter)
        
        splitter.SplitVertically(self.tree, self.properties_panel, 700)
        splitter.SetMinimumPaneSize(200)
        main_sizer.Add(splitter, 1, wx.EXPAND | wx.ALL, 5)

        # Totals area
        totals_sizer = wx.BoxSizer(wx.HORIZONTAL)
        totals_sizer.SetMinSize((-1, 40))
        self.base_total_lbl = wx.StaticText(self, label="Coût de base: 0.00 €")
        totals_sizer.Add(self.base_total_lbl, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        totals_sizer.AddSpacer(20)
        self.margin_total_lbl = wx.StaticText(self, label="Marges: 0.00 €")
        totals_sizer.Add(self.margin_total_lbl, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        totals_sizer.AddSpacer(20)
        self.total_with_margin_lbl = wx.StaticText(self, label="Total: 0.00 €")
        self.total_with_margin_lbl.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        totals_sizer.Add(self.total_with_margin_lbl, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        main_sizer.Add(totals_sizer, 0, wx.EXPAND | wx.BG_STYLE_COLOUR, 0)

        self.SetSizer(main_sizer)

    def _create_properties_panel(self, parent):
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(wx.Colour(245, 245, 245))
        sizer = wx.BoxSizer(wx.VERTICAL)

        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.properties_title = wx.StaticText(panel, label="Propriétés")
        self.properties_title.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        header_sizer.Add(self.properties_title, 1, wx.ALL | wx.ALIGN_CENTER, 10)

        self.save_properties_btn = wx.Button(panel, label="Appliquer")
        self.save_properties_btn.Bind(wx.EVT_BUTTON, self._on_save_properties)
        header_sizer.Add(self.save_properties_btn, 0, wx.ALL, 5)

        sizer.Add(header_sizer, 0, wx.EXPAND)
        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        self.properties_content = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.properties_content, 1, wx.EXPAND)

        panel.SetSizer(sizer)
        return panel

    def load_project(self, project):
        self.project = project
        self.title.SetLabel(f"Structure du projet – {project.name}")
        self._refresh_tree()
        self._update_totals()

    def _refresh_tree(self):
        self.tree.DeleteAllItems()
        if not self.project: return
        self.root = self.tree.AddRoot(f"📁 {self.project.name} (Réf: {self.project.reference})")
        for operation in self.project.operations:
            self._add_operation_to_tree(operation, self.root)
        self.tree.Expand(self.root)

    def _add_operation_to_tree(self, operation, parent):
        op_item = self.tree.AppendItem(parent, f"🔧 {operation.code} | {operation.label}")
        self.tree.SetItemData(op_item, {"type": "operation", "operation": operation})
        for cost_name, cost in operation.costs.items():
            self._add_cost_to_tree(cost, op_item, operation)
        return op_item

    def _add_cost_to_tree(self, cost, parent, operation):
        cost_icon = "💰" if cost.cost_type in [CostType.MATERIAL, CostType.SUBCONTRACTING] else "⚙️" if cost.cost_type == CostType.INTERNAL_OPERATION else "📈"
        cost_item = self.tree.AppendItem(parent, f"{cost_icon} {cost.name}")
        self.tree.SetItemData(cost_item, {"type": "cost", "cost": cost, "operation": operation})
        return cost_item

    def _on_tree_selection_changed(self, event):
        item = event.GetItem()
        if item.IsOk() and item != self.root:
            data = self.tree.GetItemData(item)
            if data:
                self._show_properties_for_item(data)
                is_op = data.get("type") == "operation"
                is_cost = data.get("type") == "cost"
                self.add_cost_btn.Enable(is_op or is_cost)
                return
        self.properties_panel.Hide()
        self.add_cost_btn.Disable()

    def _show_properties_for_item(self, data):
        self.properties_content.Clear(True)
        self.current_data = data
        self.properties_panel.Show()

        if data["type"] == "operation":
            op = data["operation"]
            self.properties_title.SetLabel(f"Opération: {op.code}")
            grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=5)
            grid.AddGrowableCol(1, 1)
            
            grid.Add(wx.StaticText(self.properties_panel, label="Code:"))
            self.prop_op_code = wx.TextCtrl(self.properties_panel, value=str(op.code))
            grid.Add(self.prop_op_code, 1, wx.EXPAND)
            
            grid.Add(wx.StaticText(self.properties_panel, label="Libellé:"))
            self.prop_op_label = wx.TextCtrl(self.properties_panel, value=str(op.label))
            grid.Add(self.prop_op_label, 1, wx.EXPAND)
            
            grid.Add(wx.StaticText(self.properties_panel, label="Pièces spéc.:"))
            self.prop_op_pieces = wx.SpinCtrl(self.properties_panel, min=1, max=1000000, initial=op.total_pieces)
            grid.Add(self.prop_op_pieces, 1, wx.EXPAND)
            
            self.properties_content.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        elif data["type"] == "cost":
            cost = data["cost"]
            self.properties_title.SetLabel(f"Coût: {cost.name}")
            grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=5)
            grid.AddGrowableCol(1, 1)
            
            grid.Add(wx.StaticText(self.properties_panel, label="Nom:"))
            self.prop_cost_name = wx.TextCtrl(self.properties_panel, value=str(cost.name))
            grid.Add(self.prop_cost_name, 1, wx.EXPAND)
            
            grid.Add(wx.StaticText(self.properties_panel, label="Type de coût:"))
            self.prop_cost_type = wx.Choice(self.properties_panel, choices=[ct.value for ct in CostType])
            self.prop_cost_type.SetStringSelection(cost.cost_type.value)
            self.prop_cost_type.Bind(wx.EVT_CHOICE, self._on_cost_type_changed)
            grid.Add(self.prop_cost_type, 1, wx.EXPAND)
            
            self.properties_content.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
            
            self.dynamic_fields_sizer = wx.BoxSizer(wx.VERTICAL)
            self._update_cost_fields(cost)
            self.properties_content.Add(self.dynamic_fields_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
            
            self.prop_comment = wx.TextCtrl(self.properties_panel, value=cost.comment or "", style=wx.TE_MULTILINE, size=(-1, 60))
            self.properties_content.Add(wx.StaticText(self.properties_panel, label="Commentaire:"), 0, wx.LEFT | wx.TOP, 10)
            self.properties_content.Add(self.prop_comment, 0, wx.EXPAND | wx.ALL, 10)

        self.properties_panel.Layout()
        self.Layout()

    def _on_cost_type_changed(self, event):
        cost = self.current_data["cost"]
        new_val = self.prop_cost_type.GetStringSelection()
        for ct in CostType:
            if ct.value == new_val:
                cost.cost_type = ct
                break
        if cost.cost_type in [CostType.MATERIAL, CostType.SUBCONTRACTING] and not cost.pricing:
            cost.pricing = PricingStructure(PricingType.FIXED)
        self._update_cost_fields(cost)
        self.properties_panel.Layout()

    def _update_cost_fields(self, cost):
        self.dynamic_fields_sizer.Clear(True)
        grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=5)
        grid.AddGrowableCol(1, 1)

        match cost.cost_type:
            case CostType.MATERIAL | CostType.SUBCONTRACTING:
                grid.Add(wx.StaticText(self.properties_panel, label="Tarification:"))
                self.prop_pricing_type = wx.Choice(self.properties_panel, choices=[pt.value for pt in PricingType])
                self.prop_pricing_type.SetStringSelection(cost.pricing.pricing_type.value)
                self.prop_pricing_type.Bind(wx.EVT_CHOICE, self._on_pricing_type_changed)
                grid.Add(self.prop_pricing_type, 1, wx.EXPAND)

                if cost.pricing.pricing_type == PricingType.FIXED:
                    grid.Add(wx.StaticText(self.properties_panel, label="Prix fixe (€):"))
                    self.prop_fixed_price = wx.TextCtrl(self.properties_panel, value=f"{cost.pricing.fixed_price:.2f}")
                    grid.Add(self.prop_fixed_price, 1, wx.EXPAND)
                elif cost.pricing.pricing_type == PricingType.PER_UNIT:
                    grid.Add(wx.StaticText(self.properties_panel, label="Prix unitaire (€):"))
                    self.prop_unit_price = wx.TextCtrl(self.properties_panel, value=f"{cost.pricing.unit_price:.2f}")
                    grid.Add(self.prop_unit_price, 1, wx.EXPAND)
                    grid.Add(wx.StaticText(self.properties_panel, label="Unité:"))
                    self.prop_unit = wx.TextCtrl(self.properties_panel, value=cost.pricing.unit)
                    grid.Add(self.prop_unit, 1, wx.EXPAND)
                elif cost.pricing.pricing_type == PricingType.TIERED:
                    grid.Add(wx.StaticText(self.properties_panel, label="Échelons:"))
                    btn = wx.Button(self.properties_panel, label="Gérer les échelons...")
                    btn.Bind(wx.EVT_BUTTON, self._on_manage_tiers)
                    grid.Add(btn, 1, wx.EXPAND)

                grid.Add(wx.StaticText(self.properties_panel, label="Réf. devis:"))
                self.prop_supplier_ref = wx.TextCtrl(self.properties_panel, value=cost.supplier_quote_ref or "")
                grid.Add(self.prop_supplier_ref, 1, wx.EXPAND)

            case CostType.INTERNAL_OPERATION:
                grid.Add(wx.StaticText(self.properties_panel, label="Temps fixe (h):"))
                self.prop_fixed_time = wx.TextCtrl(self.properties_panel, value=f"{cost.fixed_time:.2f}")
                grid.Add(self.prop_fixed_time, 1, wx.EXPAND)
                grid.Add(wx.StaticText(self.properties_panel, label="Temps/pièce (h):"))
                self.prop_per_piece_time = wx.TextCtrl(self.properties_panel, value=f"{cost.per_piece_time:.3f}")
                grid.Add(self.prop_per_piece_time, 1, wx.EXPAND)

            case CostType.MARGIN:
                grid.Add(wx.StaticText(self.properties_panel, label="Marge (%):"))
                self.prop_margin_pct = wx.TextCtrl(self.properties_panel, value=f"{cost.margin_percentage:.1f}")
                grid.Add(self.prop_margin_pct, 1, wx.EXPAND)

        self.dynamic_fields_sizer.Add(grid, 1, wx.EXPAND)
        self.dynamic_fields_sizer.Layout()

    def _on_pricing_type_changed(self, event):
        cost = self.current_data["cost"]
        new_val = self.prop_pricing_type.GetStringSelection()
        for pt in PricingType:
            if pt.value == new_val:
                cost.pricing.pricing_type = pt
                break
        self._update_cost_fields(cost)
        self.properties_panel.Layout()

    def _on_save_properties(self, event):
        data = self.current_data
        if not data: return
        try:
            if data["type"] == "operation":
                op = data["operation"]
                op.code = self.prop_op_code.GetValue()
                op.label = self.prop_op_label.GetValue()
                op.total_pieces = self.prop_op_pieces.GetValue()
                item = self.tree.GetSelection()
                self.tree.SetItemText(item, f"🔧 {op.code} | {op.label}")
            elif data["type"] == "cost":
                cost = data["cost"]
                cost.name = self.prop_cost_name.GetValue()
                cost.comment = self.prop_comment.GetValue() or None
                if cost.cost_type in [CostType.MATERIAL, CostType.SUBCONTRACTING]:
                    if cost.pricing.pricing_type == PricingType.FIXED:
                        cost.pricing.fixed_price = float(self.prop_fixed_price.GetValue())
                    elif cost.pricing.pricing_type == PricingType.PER_UNIT:
                        cost.pricing.unit_price = float(self.prop_unit_price.GetValue())
                        cost.pricing.unit = self.prop_unit.GetValue()
                    cost.supplier_quote_ref = self.prop_supplier_ref.GetValue() or None
                elif cost.cost_type == CostType.INTERNAL_OPERATION:
                    cost.fixed_time = float(self.prop_fixed_time.GetValue())
                    cost.per_piece_time = float(self.prop_per_piece_time.GetValue())
                elif cost.cost_type == CostType.MARGIN:
                    cost.margin_percentage = float(self.prop_margin_pct.GetValue())
                
                item = self.tree.GetSelection()
                cost_icon = "💰" if cost.cost_type in [CostType.MATERIAL, CostType.SUBCONTRACTING] else "⚙️" if cost.cost_type == CostType.INTERNAL_OPERATION else "📈"
                self.tree.SetItemText(item, f"{cost_icon} {cost.name}")

            self._update_totals()
            if self.on_operation_updated:
                self.on_operation_updated(data.get("operation"))
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'enregistrement: {str(e)}", "Erreur")

    def _on_add_operation(self, event):
        op = Operation(code="NOUV", label="Nouvelle opération")
        self.project.add_operation(op)
        item = self._add_operation_to_tree(op, self.root)
        self.tree.SelectItem(item)
        if self.on_operation_updated: self.on_operation_updated(op)

    def _on_add_cost_to_selected_op(self, event):
        item = self.tree.GetSelection()
        if not item.IsOk(): return
        data = self.tree.GetItemData(item)
        op = data["operation"] if data else None
        if not op: return
        
        choices = [ct.value for ct in CostType]
        dlg = wx.SingleChoiceDialog(self, "Type de Coût", "Nouveau coût", choices)
        if dlg.ShowModal() == wx.ID_OK:
            ct = list(CostType)[dlg.GetSelection()]
            name = f"Nouveau {ct.value.lower()}"
            i = 1
            while name in op.costs:
                name = f"Nouveau {ct.value.lower()} {i}"
                i += 1
            
            pricing = PricingStructure(PricingType.FIXED)
            cost = CostItem(name, ct, pricing)
            op.costs[name] = cost
            
            op_item = item if data["type"] == "operation" else self.tree.GetItemParent(item)
            cost_item = self._add_cost_to_tree(cost, op_item, op)
            self.tree.Expand(op_item)
            self.tree.SelectItem(cost_item)
            if self.on_operation_updated: self.on_operation_updated(op)

    def _on_delete(self, event):
        item = self.tree.GetSelection()
        if not item.IsOk() or item == self.root: return
        data = self.tree.GetItemData(item)
        if wx.MessageBox("Confirmer la suppression ?", "Confirmation", wx.YES_NO) != wx.YES: return
        
        if data["type"] == "operation":
            self.project.operations.remove(data["operation"])
        else:
            del data["operation"].costs[data["cost"].name]
        
        self.tree.Delete(item)
        self._update_totals()
        if self.on_operation_updated: self.on_operation_updated(None)

    def _on_duplicate(self, event):
        item = self.tree.GetSelection()
        if not item.IsOk() or item == self.root: return
        data = self.tree.GetItemData(item)
        
        if data["type"] == "operation":
            op = data["operation"]
            new_op = Operation(code=f"{op.code}_copie", label=f"{op.label} (copie)", total_pieces=op.total_pieces)
            new_op.costs = copy.deepcopy(op.costs)
            self.project.add_operation(new_op)
            new_item = self._add_operation_to_tree(new_op, self.root)
            self.tree.SelectItem(new_item)
        else:
            op = data["operation"]
            cost = data["cost"]
            new_cost = copy.deepcopy(cost)
            new_name = f"{cost.name} (copie)"
            i = 1
            while new_name in op.costs:
                new_name = f"{cost.name} (copie {i})"
                i += 1
            new_cost.name = new_name
            op.costs[new_name] = new_cost
            new_item = self._add_cost_to_tree(new_cost, self.tree.GetItemParent(item), op)
            self.tree.SelectItem(new_item)
        self._update_totals()

    def _on_move_up(self, event):
        # Simplifié pour le moment
        pass

    def _on_move_down(self, event):
        # Simplifié pour le moment
        pass

    def _on_pieces_changed(self, event):
        val = self.pieces_ctrl.GetValue()
        for op in self.project.operations:
            op.total_pieces = val
        self._update_totals()
        if self.on_operation_updated: self.on_operation_updated(None)

    def _update_totals(self):
        if not self.project: return
        base = sum(op.total_cost() for op in self.project.operations)
        total = sum(op.total_with_margins() for op in self.project.operations)
        self.base_total_lbl.SetLabel(f"Coût de base: {base:.2f} €")
        self.margin_total_lbl.SetLabel(f"Marges: {total-base:.2f} €")
        self.total_with_margin_lbl.SetLabel(f"Total: {total:.2f} €")

    def _on_manage_tiers(self, event):
        cost = self.current_data["cost"]
        dlg = TiersEditorDialog(self, cost.pricing.tiers)
        if dlg.ShowModal() == wx.ID_OK:
            cost.pricing.tiers = dlg.get_tiers()
            self._update_totals()
        dlg.Destroy()

    def _on_tree_end_label_edit(self, event):
        if event.IsEditCancelled(): return
        item = event.GetItem()
        new_label = event.GetLabel()
        data = self.tree.GetItemData(item)
        if data["type"] == "operation":
            data["operation"].label = new_label
        else:
            data["cost"].name = new_label
        if self.on_operation_updated: self.on_operation_updated(None)

    def _on_tree_right_click(self, event):
        item = event.GetItem()
        if item.IsOk() and item != self.root:
            self.tree.SelectItem(item)
            menu = wx.Menu()
            ren = menu.Append(wx.ID_ANY, "Renommer")
            self.Bind(wx.EVT_MENU, lambda e: self.tree.EditLabel(item), ren)
            del_item = menu.Append(wx.ID_ANY, "Supprimer")
            self.Bind(wx.EVT_MENU, self._on_delete, del_item)
            self.PopupMenu(menu)
            menu.Destroy()

class TiersEditorDialog(wx.Dialog):
    def __init__(self, parent, tiers):
        super().__init__(parent, title="Gestion des échelons", size=(500, 400))
        self.tiers = copy.deepcopy(tiers)
        self._init_ui()

    def _init_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list.InsertColumn(0, "Qté Min", width=80)
        self.list.InsertColumn(1, "Qté Max", width=80)
        self.list.InsertColumn(2, "Prix Unitaire", width=100)
        self._refresh_list()
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(self, label="Ajouter")
        add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        btn_sizer.Add(add_btn, 0, wx.ALL, 5)
        
        del_btn = wx.Button(self, label="Supprimer")
        del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        btn_sizer.Add(del_btn, 0, wx.ALL, 5)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER)
        
        line = wx.StaticLine(self)
        sizer.Add(line, 0, wx.EXPAND | wx.ALL, 5)
        
        db_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(db_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        self.SetSizer(sizer)

    def _refresh_list(self):
        self.list.DeleteAllItems()
        self.tiers.sort(key=lambda t: t.min_quantity)
        for i, t in enumerate(self.tiers):
            self.list.InsertItem(i, str(t.min_quantity))
            self.list.SetItem(i, 1, str(t.max_quantity) if t.max_quantity else "∞")
            self.list.SetItem(i, 2, f"{t.unit_price:.2f}")

    def _on_add(self, event):
        dlg = SingleTierDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            self.tiers.append(dlg.get_tier())
            self._refresh_list()
        dlg.Destroy()

    def _on_delete(self, event):
        idx = self.list.GetFirstSelected()
        if idx != -1:
            del self.tiers[idx]
            self._refresh_list()

    def get_tiers(self):
        return self.tiers

class SingleTierDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Nouvel échelon", size=(300, 200))
        grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=10)
        
        grid.Add(wx.StaticText(self, label="Quantité Min:"))
        self.min_q = wx.SpinCtrl(self, min=0, max=1000000)
        grid.Add(self.min_q, 1, wx.EXPAND)
        
        grid.Add(wx.StaticText(self, label="Quantité Max:"))
        self.max_q = wx.TextCtrl(self, value="")
        grid.Add(self.max_q, 1, wx.EXPAND)
        
        grid.Add(wx.StaticText(self, label="Prix Unitaire:"))
        self.price = wx.TextCtrl(self, value="0.0")
        grid.Add(self.price, 1, wx.EXPAND)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 15)
        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_CENTER | wx.ALL, 10)
        self.SetSizer(sizer)

    def get_tier(self):
        mq = self.max_q.GetValue().strip()
        return PricingTier(
            min_quantity=self.min_q.GetValue(),
            max_quantity=int(mq) if mq else None,
            unit_price=float(self.price.GetValue())
        )
