# ui/panels/operation_cost_editor_panel.py
import wx
import copy
from datetime import datetime
import domain.cost as domain_cost
from domain.operation import (Operation, SUBCONTRACTING_TYPOLOGY, TOOLING_TYPOLOGY,
                               INTERNAL_TYPOLOGY, OPERATION_TYPOLOGIES, normalize_typology,
                               family_from_typology)
from domain.phase import ToolingBilling, PhaseKind
from ui.components.step_summary_panel import StepSummaryPanel
from ui.components.offer_info_panel import OfferInfoPanel
from ui.components.cost_item_editor import CostItemEditor
from ui.components.offers_comparison_grid import OffersComparisonGrid
from ui.components.ribbon_button import RibbonButton, ACCENT, DANGER, TOOLING, SURFACE
from infrastructure.configuration import ConfigurationService
from infrastructure.logging_service import get_module_logger
from infrastructure.template_manager import TemplateManager

logger = get_module_logger("OperationCostEditor", "operation_cost_editor.log")

NO_TEMPLATE = "Aucun"

class OperationCostEditorPanel(wx.Panel):
    """Panel pour éditer les opérations du projet et leurs coûts associés."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.on_operation_updated = None
        self.current_data = None
        self.config_service = ConfigurationService()
        self.template_manager = None
        self._locked = False                 # version figée par une offre émise
        self.on_request_new_version = None   # callback → MainFrame._on_add_version
        self._build_ui()

    def _build_ui(self):
        # Use a SplitterWindow for resizable panels
        splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        # Left side: Tree
        left_panel = wx.Panel(splitter)
        left_panel.SetBackgroundColour(wx.WHITE)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        # Bandeau « ruban » : les deux seules actions de niveau Gamme
        ribbon = wx.Panel(left_panel)
        ribbon.SetBackgroundColour(SURFACE)
        ribbon_sizer = wx.BoxSizer(wx.VERTICAL)
        caption = wx.StaticText(ribbon, label="GAMME")
        caption.SetFont(wx.Font(wx.FontInfo(8).FaceName("Segoe UI").Bold()))
        caption.SetForegroundColour(wx.Colour(100, 116, 139))
        ribbon_sizer.Add(caption, 0, wx.LEFT | wx.TOP, 10)
        ribbon_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add_op = RibbonButton(ribbon, "➕", "Ajouter", accent=ACCENT, big=True, size=(130, 78))
        self.btn_add_op.SetToolTip("Ajouter une opération à la gamme")
        self.btn_add_op.Bind(wx.EVT_BUTTON, self._on_add_operation)
        self.btn_del_op = RibbonButton(ribbon, "🗑", "Supprimer", accent=DANGER, big=True, size=(130, 78))
        self.btn_del_op.SetToolTip("Supprimer l'opération sélectionnée (et ses lignes)")
        self.btn_del_op.Bind(wx.EVT_BUTTON, self._on_delete_operation)
        ribbon_btns.Add(self.btn_add_op, 0, wx.RIGHT, 8)
        ribbon_btns.Add(self.btn_del_op, 0)
        ribbon_sizer.Add(ribbon_btns, 0, wx.ALL, 10)
        ribbon.SetSizer(ribbon_sizer)
        left_sizer.Add(ribbon, 0, wx.EXPAND)
        left_sizer.Add(wx.StaticLine(left_panel), 0, wx.EXPAND)

        self.tree = wx.TreeCtrl(left_panel, style=wx.TR_HAS_BUTTONS | wx.TR_EDIT_LABELS | wx.BORDER_NONE)
        self.tree.SetFont(wx.Font(wx.FontInfo(10).FaceName("Segoe UI")))
        self.tree.SetBackgroundColour(wx.WHITE)
        self.root = self.tree.AddRoot("Projet")
        left_sizer.Add(self.tree, 1, wx.EXPAND | wx.ALL, 5)
        left_panel.SetSizer(left_sizer)

        # Right side: Detail Panel
        self.properties_panel = wx.ScrolledWindow(splitter, style=wx.VSCROLL)
        self.properties_panel.SetScrollRate(0, 20)
        self.properties_panel.SetBackgroundColour(wx.WHITE)
        self.properties_content = wx.BoxSizer(wx.VERTICAL)
        
        # -1. Ajout d'éléments enfants de l'opération sélectionnée (étape/offre, outillage)
        self.children_bar = wx.Panel(self.properties_panel)
        self.children_bar.SetBackgroundColour(SURFACE)
        children_sizer = wx.WrapSizer(wx.HORIZONTAL)
        self.btn_add_cost = RibbonButton(self.children_bar, "⚙", "Nouvelle étape",
                                         "Temps × taux horaire", accent=ACCENT, size=(230, 54))
        self.btn_add_cost.Bind(wx.EVT_BUTTON, self._on_add_cost_to_selected_op)
        self.btn_add_tooling = RibbonButton(self.children_bar, "🛠", "Nouvel outillage",
                                            "Montant, détail, pièces fournies", accent=TOOLING, size=(250, 54))
        self.btn_add_tooling.Bind(wx.EVT_BUTTON, self._on_add_tooling_cost_to_selected_op)
        children_sizer.Add(self.btn_add_cost, 0, wx.ALL, 8)
        children_sizer.Add(self.btn_add_tooling, 0, wx.ALL, 8)
        self.children_bar.SetSizer(children_sizer)
        self.properties_content.Add(self.children_bar, 0, wx.EXPAND)
        self.children_bar.Hide()

        # 0. Phases de l'élément sélectionné (opération ou ligne)
        self.phase_row = wx.Panel(self.properties_panel)
        self.phase_row.SetBackgroundColour(wx.Colour(240, 244, 250))
        self.phase_row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.phase_row.SetSizer(self.phase_row_sizer)
        self.properties_content.Add(self.phase_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.phase_row.Hide()

        # 1. Operation specific properties
        self.op_props_panel = wx.Panel(self.properties_panel)
        self.op_props_panel.SetBackgroundColour(wx.WHITE)
        self.op_props_sizer = wx.BoxSizer(wx.VERTICAL) # Changed to self.op_props_sizer
        
        # Modèle (template) : liste déroulante, « Aucun » par défaut. Choisir un
        # modèle reconfigure l'opération (lignes, commentaire).
        tpl_row = wx.BoxSizer(wx.HORIZONTAL)
        tpl_row.Add(wx.StaticText(self.op_props_panel, label="Modèle :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.template_choice = wx.Choice(self.op_props_panel, choices=[NO_TEMPLATE])
        self.template_choice.SetSelection(0)
        self.template_choice.Bind(wx.EVT_CHOICE, self._on_template_chosen)
        tpl_row.Add(self.template_choice, 1, wx.EXPAND)
        self.op_props_sizer.Add(tpl_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self._template_options = []
        self.template_status = wx.StaticText(self.op_props_panel, label="")
        self.template_status.SetForegroundColour(wx.Colour(170, 90, 0))
        self.op_props_sizer.Add(self.template_status, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Fixed grid for Typology and Label
        grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self.op_props_panel, label="Type d'opération:"))
        self.prop_op_typology = wx.Choice(self.op_props_panel, choices=OPERATION_TYPOLOGIES)
        grid.Add(self.prop_op_typology, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self.op_props_panel, label="Famille:"), 0, wx.ALIGN_CENTER_VERTICAL)
        families = [t for t in self.config_service.get_cost_typologies()
                    if t.strip() not in OPERATION_TYPOLOGIES]
        self.prop_op_family = wx.ComboBox(self.op_props_panel, choices=families)
        self.prop_op_family.SetToolTip("Famille d'usinage (optionnelle) : sert aux analyses et exports, pas au calcul.")
        grid.Add(self.prop_op_family, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self.op_props_panel, label="Libellé:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.prop_op_label = wx.TextCtrl(self.op_props_panel)
        grid.Add(self.prop_op_label, 1, wx.EXPAND)
        
        self.op_props_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        
        # Commentaire de chiffrage de l'opération : 5-6 lignes suffisent
        comment_sizer = wx.BoxSizer(wx.VERTICAL)
        comment_sizer.Add(wx.StaticText(self.op_props_panel, label="Commentaire de chiffrage:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.prop_op_comment = wx.TextCtrl(self.op_props_panel, style=wx.TE_MULTILINE | wx.TE_WORDWRAP, size=(-1, 100))
        self.prop_op_comment.SetMinSize((-1, 100))
        comment_sizer.Add(self.prop_op_comment, 0, wx.EXPAND | wx.ALL, 5)
        self.op_props_sizer.Add(comment_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Synthèse : prix de vente de chaque étape et prix global de l'opération, par quantité
        self.step_summary = StepSummaryPanel(self.op_props_panel)
        self.op_props_sizer.Add(self.step_summary, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Sous-traitance : informations de l'offre retenue (les simulations par quantité vivent dans le récapitulatif)
        self.offer_info = OfferInfoPanel(self.op_props_panel)
        self.offer_info.Hide()
        self.op_props_sizer.Add(self.offer_info, 0, wx.EXPAND | wx.ALL, 5)
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


        self.properties_placeholder = wx.StaticText(self.properties_panel, label="Sélectionnez un élément")
        self.properties_content.Add(self.properties_placeholder, 0, wx.ALL, 20)

        # Les changements sont maintenant appliqués "à la volée" (On-the-fly)
        # On ne crée plus de bouton de sauvegarde globale.

        self.properties_panel.SetSizer(self.properties_content)

        # Split the window: left panel for tree, right panel for properties
        # SplitVertically creates two panes left-right
        splitter.SplitVertically(left_panel, self.properties_panel)
        # Set the initial sash position (proportion of left side width)
        splitter.SetSashPosition(340)  # largeur du ruban (2 gros boutons) + arbre
        splitter.SetMinimumPaneSize(200)  # Minimum size for each pane to allow resizing
        
        # Bandeau « version figée » (affiché seulement quand une offre a été émise)
        self.lock_banner = wx.Panel(self)
        self.lock_banner.SetBackgroundColour(wx.Colour(255, 247, 230))
        banner_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.lock_text = wx.StaticText(self.lock_banner, label="")
        self.lock_text.SetFont(wx.Font(wx.FontInfo(10).FaceName("Segoe UI")))
        self.lock_text.SetForegroundColour(wx.Colour(130, 80, 0))
        banner_sizer.Add(self.lock_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 10)
        self.btn_new_version = RibbonButton(self.lock_banner, "➕", "Nouvelle version",
                                            "Copie de cette gamme, modifiable", accent=TOOLING, size=(250, 50))
        self.btn_new_version.Bind(wx.EVT_BUTTON, self._on_request_new_version)
        banner_sizer.Add(self.btn_new_version, 0, wx.ALL, 6)
        self.lock_banner.SetSizer(banner_sizer)
        self.lock_banner.Hide()

        # Main sizer for the panel
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self.lock_banner, 0, wx.EXPAND)
        main_sizer.Add(splitter, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_selection_changed)
        self.tree.Bind(wx.EVT_TREE_END_LABEL_EDIT, self._on_tree_end_label_edit)
        self.tree.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self._on_tree_right_click)
        self.tree.Bind(wx.EVT_TREE_KEY_DOWN, self._on_tree_key_down)

        # Bind events for the Operation properties
        self.prop_op_typology.Bind(wx.EVT_CHOICE, self._on_op_field_changed)
        self.prop_op_family.Bind(wx.EVT_TEXT, self._on_op_field_changed)
        self.prop_op_family.Bind(wx.EVT_COMBOBOX, self._on_op_field_changed)
        self.prop_op_label.Bind(wx.EVT_TEXT, self._on_op_field_changed)
        self.prop_op_comment.Bind(wx.EVT_TEXT, self._on_op_field_changed)
        self.prop_op_label.Bind(wx.EVT_TEXT, self._on_op_field_changed)
        self.prop_op_comment.Bind(wx.EVT_TEXT, self._on_op_field_changed)

    # ------------------------------------------------------------------ verrouillage

    @property
    def is_locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool, frozen_by: str = "") -> None:
        """Gamme figée (offre émise) : lecture seule, avec bandeau et accès à « Nouvelle version »."""
        self._locked = bool(locked)
        if locked:
            who = f" (offre {frozen_by})" if frozen_by else ""
            self.lock_text.SetLabel(f"🔒  Version émise{who} : la gamme est figée. "
                                    "Pour la modifier, créez une nouvelle version.")
        self.lock_banner.Show(self._locked)
        self.properties_panel.Enable(not self._locked)
        self.btn_add_op.Enable(not self._locked)
        self.btn_del_op.Enable(not self._locked)
        self.Layout()

    def _blocked(self) -> bool:
        """Vrai (et signal sonore) si la gamme est figée : l'action de modification est refusée."""
        if self._locked:
            wx.Bell()
        return self._locked

    def _on_request_new_version(self, event):
        if callable(self.on_request_new_version):
            self.on_request_new_version()

    def load_project(self, project):
        self.project = project
        logger.info(f"load_project | ops={len(project.operations) if project else 0}")
        if self.project:
            for op in self.project.operations:
                op.typology = normalize_typology(op.typology)
                self._enforce_operation_constraints(op)
        self._refresh_tree()

    def get_selection_path(self):
        """Identifiant stable (indépendant des objets) de la sélection courante.

        Retourne (op_index, cost_key_or_None) ou None si rien de sélectionné.
        Permet de restaurer la même position après un rechargement/changement de version.
        """
        data = self.current_data
        if not data or not self.project:
            return None
        op = data.get("operation")
        if op is None:
            return None
        try:
            op_index = self.project.operations.index(op)
        except ValueError:
            return None
        if data.get("type") == "cost":
            return (op_index, data.get("cost_key"))
        return (op_index, None)

    def restore_selection_path(self, path):
        """Restaure la sélection à partir d'un path (op_index, cost_key_or_None)."""
        if not path or not self.project:
            return
        op_index, cost_key = path
        if op_index < 0 or op_index >= len(self.project.operations):
            return
        op = self.project.operations[op_index]
        op_item = self._find_item_by_op(op, self.root)
        if not op_item or not op_item.IsOk():
            return
        if cost_key is not None:
            cost = op.costs.get(cost_key)
            if cost is not None:
                cost_item = self._find_item_by_cost(cost, op_item)
                if cost_item and cost_item.IsOk():
                    self.tree.SelectItem(cost_item)
                    self.tree.EnsureVisible(cost_item)
                    return
        # Repli : sélectionner l'opération
        self.tree.SelectItem(op_item)
        self.tree.EnsureVisible(op_item)

    def set_database(self, db):
        self.template_manager = TemplateManager(db)

    def refresh_data(self):
        """Rafraîchit l'affichage sans recharger l'arbre (pour cohérence avec les autres panels)."""
        if self.op_props_panel.IsShown() and self.current_data and self.current_data["type"] == "operation":
            self.step_summary.load(self.current_data["operation"], self.project)
            if self.offer_info.IsShown():
                self.offer_info.load(self.current_data["operation"], self.project)
        # Rafraîchir la grille de comparaison si visible
        if self.comparison_grid.IsShown() and self.current_data:
            if self.current_data["type"] == "operation":
                self.comparison_grid.load_operation(self.current_data["operation"], self.project)

    def refresh_quantities(self):
        """Rafraîchit les sélecteurs de quantités dans les sous-composants."""

    def update_root_label(self):
        """Update only the root item label based on the current project reference."""
        if self.project and self.root and self.root.IsOk():
            ref = self.project.reference if self.project.reference else "Projet"
            self.tree.SetItemText(self.root, ref)

    def reload_selected_properties(self):
        """Recharge le panneau de propriétés (valeurs modifiées depuis un autre onglet)."""
        if self.current_data:
            self._show_properties(self.current_data)

    def _op_label(self, op):
        return f"🔧 {op.display_family or 'Op'} | {op.label}"

    def _cost_label(self, cost, op):
        if cost.cost_type == domain_cost.CostType.INTERNAL_OPERATION and getattr(cost, 'is_temps_masque', False):
            cost_icon = "⏱️"
        else:
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
        if cost.cost_type == domain_cost.CostType.TOOLING and cost.tooling_billing is not None:
            label += f"  ({cost.tooling_billing.value})"
        return label

    def _cost_colour(self, cost, op):
        if op.typology == SUBCONTRACTING_TYPOLOGY and not cost.is_active:
            return wx.Colour(150, 150, 150)
        return wx.BLACK

    def _op_colour(self, op):
        return wx.BLACK

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
        item = self.tree.AppendItem(parent, self._op_label(op))
        self.tree.SetItemTextColour(item, self._op_colour(op))
        self.tree.SetItemData(item, {"type": "operation", "operation": op})
        for cost_name, cost in op.costs.items():
            self._add_cost_to_tree(cost, item, op, cost_name)
        return item

    def _add_cost_to_tree(self, cost, parent, op, cost_key=None):
        if not parent or not parent.IsOk(): return None
        item = self.tree.AppendItem(parent, self._cost_label(cost, op))
        self.tree.SetItemTextColour(item, self._cost_colour(cost, op))
        self.tree.SetItemData(item, {"type": "cost", "cost": cost, "operation": op, "cost_key": cost_key or cost.name})
        return item

    def _refresh_operation_items(self, op):
        """Update only the hierarchy of a single operation in the tree."""
        op_item = self._find_item_by_op(op, self.root)
        if not op_item or not op_item.IsOk():
            return
            
        # 1. Update Op label
        self.tree.SetItemText(op_item, self._op_label(op))
        self.tree.SetItemTextColour(op_item, self._op_colour(op))

        # 2. Update Costs (labels/colors/icons)
        child, cookie = self.tree.GetFirstChild(op_item)
        while child.IsOk():
            data = self.tree.GetItemData(child)
            if data and data["type"] == "cost":
                cost = data["cost"]
                self.tree.SetItemTextColour(child, self._cost_colour(cost, op))
                self.tree.SetItemText(child, self._cost_label(cost, op))

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
        self.phase_row.Hide()
        self.children_bar.Hide()
        self.properties_placeholder.Show()
        self.properties_panel.Layout()

    def _show_properties(self, data):
        self.properties_placeholder.Hide()
        self._load_children_bar(data["operation"])
        self._load_phase_row(data)

        if data["type"] == "operation":
            self.cost_editor.Hide()
            self.op_props_panel.Show()
            op = data["operation"]
            
            self._apply_op_type_layout(op)
                
            # Freeze to avoid flickers during value setting
            self.op_props_panel.Freeze()
            if op.typology:
                self.prop_op_typology.SetStringSelection(op.typology)
            else:
                self.prop_op_typology.SetSelection(0)
            self.prop_op_family.ChangeValue(op.family or "")
            self.prop_op_label.ChangeValue(op.label or "")
            self.prop_op_comment.ChangeValue(op.comment or "")
            self._populate_template_choice(op)
            self.op_props_panel.Thaw() # Restore Thaw
            
            self.step_summary.load(op, self.project)
            self._update_template_flag(op)
        else:
            self.op_props_panel.Hide()
            self.cost_editor.Show()
            self.cost_editor.load_cost(data["cost"], self.project)
        
        # Ensure sizer and panel are correctly recalculated to avoid overlaps
        self.properties_content.Layout()
        self.properties_panel.Layout()
        # Zone défilante : le contenu garde sa hauteur minimale (tableau de synthèse compris)
        self.properties_panel.FitInside()

    def _apply_op_type_layout(self, op):
        """Panneaux d'aperçu selon le type : Interne → récapitulatif par quantité ; Sous-traitance →
        offre retenue + comparaison des offres."""
        is_st = op.typology == SUBCONTRACTING_TYPOLOGY
        self.step_summary.Show(not is_st)   # une offre = une ligne : le détail de l'offre le remplace
        self.offer_info.Show(is_st)
        self.comparison_grid.Show(is_st)
        if is_st:
            self.offer_info.load(op, self.project)
            self.comparison_grid.load_operation(op, self.project)
        else:
            self.step_summary.load(op, self.project)

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
            op.refresh_free_pieces()  # pièces fournies / rattachement d'outillage modifiés
            if self.template_manager and getattr(op, "template_id", None):
                op.template_drift_score = self.template_manager.compute_drift_score(op)
                self._update_template_flag(op)
            # 2.1 Exclusive activation for Subcontracting
            from domain.operation import SUBCONTRACTING_TYPOLOGY
            if op.typology == SUBCONTRACTING_TYPOLOGY and cost.cost_type == domain_cost.CostType.SUBCONTRACTING and cost.is_active:
                for other_cost in op.costs.values():
                    if other_cost is not cost and other_cost.cost_type == domain_cost.CostType.SUBCONTRACTING:
                        other_cost.is_active = False
                
                # Optimized: update only current operation subtree
                self._refresh_operation_items(op)
            else:
                # Update only current label to match current state (handles typing)
                item = self.tree.GetSelection()
                if item and item.IsOk():
                    self.tree.SetItemTextColour(item, self._cost_colour(cost, op))
                    self.tree.SetItemText(item, self._cost_label(cost, op))

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
        previous_typology = op.typology
        op.typology = self.prop_op_typology.GetStringSelection() or INTERNAL_TYPOLOGY
        op.family = self.prop_op_family.GetValue().strip()
        # op.code reste stable (clé des postes machine série) : il n'est plus
        # écrasé par la typologie.
        op.label = self.prop_op_label.GetValue().strip()
        op.comment = self.prop_op_comment.GetValue()
        self._enforce_operation_constraints(op)
        if self.template_manager and getattr(op, "template_id", None):
            op.template_drift_score = self.template_manager.compute_drift_score(op)
        after_state = [(k, v.cost_type.value, v.name) for k, v in op.costs.items()]
        
        # Update Tree Label
        item = self.tree.GetSelection()
        if item.IsOk():
            self.tree.SetItemText(item, self._op_label(op))
            if before_state != after_state:
                self._refresh_tree()
                new_item = self._find_item_by_op(op, self.root)
                if new_item:
                    self.tree.SelectItem(new_item)
            
        # Changement Interne ↔ Sous-traitance : barre d'ajout et panneaux d'aperçu suivent aussitôt
        if op.typology != previous_typology:
            self._load_children_bar(op)
            self._apply_op_type_layout(op)
            self.properties_content.Layout()
            self.properties_panel.Layout()
            self.properties_panel.FitInside()
        elif op.typology == SUBCONTRACTING_TYPOLOGY:
            self.offer_info.load(op, self.project)
        self.step_summary.load(op, self.project)
        self._update_template_flag(op)
        
        # Notify main frame
        if self.on_operation_updated:
            self.on_operation_updated(None)

    def _new_operation_code(self) -> str:
        """Code unique et stable (sert de clé aux postes machine série)."""
        used = {op.code for op in self.project.operations} if self.project else set()
        n = 1
        while f"OP{n}" in used:
            n += 1
        return f"OP{n}"

    def _on_add_operation(self, event):
        if self._blocked():
            return
        op = Operation(code=self._new_operation_code(), label="Nouvelle", typology=INTERNAL_TYPOLOGY)
        self.project.add_operation(op)
        self._refresh_tree()
        self._select_after_phase_change(op)
        if self.on_operation_updated:
            self.on_operation_updated(op, reload_header=True)

    # ------------------------------------------------------------------ enfants & modèles

    def _load_children_bar(self, op):
        """Libellés des ajouts selon le type d'opération (Interne / Sous-traitance)."""
        if op.typology == SUBCONTRACTING_TYPOLOGY:
            self.btn_add_cost.set_label("Nouvelle offre", "Prix, échelons, pièces consommées")
            self.btn_add_cost._icon = "🧾"
        else:
            self.btn_add_cost.set_label("Nouvelle étape", "Temps × taux horaire")
            self.btn_add_cost._icon = "⚙"
        self.children_bar.Show()
        self.children_bar.Layout()

    def _populate_template_choice(self, op):
        """Remplit la liste des modèles ; « Aucun » sauf si l'opération en suit un."""
        items = [NO_TEMPLATE]
        self._template_options = []
        if self.template_manager:
            try:
                self._template_options = self.template_manager.list_templates()
            except Exception:
                logger.exception("list_templates failed")
                self._template_options = []
        items += [f"{t['name']}  ·  {t['typology'] or '—'}" for t in self._template_options]
        self.template_choice.Set(items)
        selected = 0
        tpl_id = getattr(op, "template_id", None)
        if tpl_id:
            for i, t in enumerate(self._template_options, start=1):
                if t["id"] == tpl_id:
                    selected = i
                    break
        self.template_choice.SetSelection(selected)

    def _on_template_chosen(self, event):
        """« Aucun » détache le modèle ; un modèle reconfigure l'opération."""
        if self._blocked():
            return
        data = self.current_data
        if not data or data.get("type") != "operation":
            return
        op = data["operation"]
        idx = self.template_choice.GetSelection()
        if idx <= 0:
            op.template_id, op.template_name = None, ""
            op.template_snapshot, op.template_drift_score = {}, 0.0
            self._update_template_flag(op)
        else:
            tpl = self._template_options[idx - 1]
            if op.costs and wx.MessageBox(
                    f"Reconfigurer « {op.label} » selon le modèle « {tpl['name']} » ?\n\n"
                    "Les lignes actuelles de l'opération seront remplacées.",
                    "Appliquer le modèle", wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
                self._populate_template_choice(op)  # revient à l'état précédent
                return
            self._apply_template(op, tpl)
        self._refresh_tree()
        self._select_after_phase_change(op)
        if self.on_operation_updated:
            self.on_operation_updated(op, reload_header=True)

    def _apply_template(self, op, tpl):
        built = self.template_manager.build_operation_from_template(tpl)
        op.costs = built.costs
        op.comment = built.comment
        op.family = family_from_typology(built.typology) or op.family
        op.typology = normalize_typology(built.typology)
        op.template_id, op.template_name = built.template_id, built.template_name
        op.template_snapshot, op.template_drift_score = built.template_snapshot, 0.0
        op.refresh_free_pieces()

    def _on_delete_operation(self, event):
        """Ruban : supprime l'opération de la sélection courante (avec confirmation)."""
        if self._blocked():
            return
        data = self.current_data
        if not data or not self.project:
            wx.MessageBox("Sélectionnez d'abord une opération.", "Supprimer l'opération",
                          wx.OK | wx.ICON_INFORMATION)
            return
        op = data["operation"]
        n = len(op.costs)
        if wx.MessageBox(f"Supprimer l'opération « {op.label} » et ses {n} ligne(s) ?",
                         "Supprimer l'opération", wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        self.project.operations.remove(op)
        self._clear_properties()
        self._refresh_tree()
        if self.on_operation_updated:
            self.on_operation_updated(None, reload_header=True)

    def _on_tree_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_DELETE and self.current_data:
            self._on_delete(None)
        else:
            event.Skip()

    def _on_save_operation_as_template(self, event):
        data = self.current_data
        if not data or data.get("type") != "operation":
            wx.MessageBox("Sélectionnez une opération d'abord.", "Template", wx.OK | wx.ICON_INFORMATION)
            return
        if not self.template_manager:
            wx.MessageBox("TemplateManager indisponible.", "Erreur", wx.OK | wx.ICON_ERROR)
            return
        op = data["operation"]
        default_name = f"{op.display_family or 'Template'} - {op.label or 'Operation'}"
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
            self.template_status.SetLabel("")
            self.template_status.SetForegroundColour(wx.Colour(120, 120, 120))
            return
        drift = float(getattr(op, "template_drift_score", 0.0) or 0.0)
        self.template_status.SetLabel(
            f"Écart au modèle « {op.template_name or '-'} » : {drift:.1f} %"
        )
        if drift >= 30:
            self.template_status.SetForegroundColour(wx.Colour(190, 60, 40))
        elif drift > 0:
            self.template_status.SetForegroundColour(wx.Colour(170, 110, 0))
        else:
            self.template_status.SetForegroundColour(wx.Colour(40, 120, 40))

    def _create_tooling_cost(self, op, base_name="Outillage"):
        """Create a tooling cost child with a unique display name."""
        name = base_name
        counter = 2
        while name in op.costs:
            name = f"{base_name} {counter}"
            counter += 1

        pricing = domain_cost.PricingStructure(domain_cost.PricingType.PER_UNIT)
        cost = domain_cost.CostItem(name, domain_cost.CostType.TOOLING, pricing)
        cost.name = name
        return cost

    def _on_add_tooling_cost_to_selected_op(self, event):
        if self._blocked():
            return
        item = self.tree.GetSelection()
        if not item.IsOk(): return
        data = self.tree.GetItemData(item)
        op = data["operation"] if data else None
        if not op: return

        cost = self._create_tooling_cost(op)
        op.costs[cost.name] = cost

        self._refresh_tree()
        if self.root and self.root.IsOk():
            op_item = self._find_item_by_op(op, self.root)
            if op_item and op_item.IsOk():
                new_item = self._find_item_by_cost(cost, op_item)
                if new_item and new_item.IsOk():
                    self.tree.SelectItem(new_item)

        if self.on_operation_updated:
            self.on_operation_updated(op, reload_header=True)

    def _on_add_cost_to_selected_op(self, event):
        if self._blocked():
            return
        item = self.tree.GetSelection()
        if not item.IsOk(): return
        data = self.tree.GetItemData(item)
        op = data["operation"] if data else None
        if not op: return

        base_name = "Nouveau coût"
        name = base_name
        counter = 1
        while name in op.costs:
            name = f"{base_name} {counter}"
            counter += 1

        # Le type de ligne découle du type d'opération : Sous-traitance → achat,
        # sinon opération interne (temps × taux). L'outillage passe par « + Outillage ».
        ct = (domain_cost.CostType.SUBCONTRACTING if op.typology == SUBCONTRACTING_TYPOLOGY
              else domain_cost.CostType.INTERNAL_OPERATION)
        pricing = domain_cost.PricingStructure(domain_cost.PricingType.PER_UNIT)
        cost = domain_cost.CostItem(name, ct, pricing)
        op.costs[name] = cost

        self._refresh_tree()
        if self.root and self.root.IsOk():
            op_item = self._find_item_by_op(op, self.root)
            if op_item and op_item.IsOk():
                new_item = self._find_item_by_cost(cost, op_item)
                if new_item and new_item.IsOk():
                    self.tree.SelectItem(new_item)

        if self.on_operation_updated:
            self.on_operation_updated(op, reload_header=True)

    def _on_delete(self, event):
        if self._blocked():
            return
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
        if self._blocked():
            event.Veto()
            return
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
            current_key = self._resolve_cost_key(op, cost, data.get("cost_key", cost.name))
            if not op.rename_cost(current_key, new_label):
                event.Veto()
                wx.MessageBox("Nom déjà utilisé ou invalide.", "Erreur")
                return
            data["cost_key"] = new_label
        if self.on_operation_updated: self.on_operation_updated(None)

    def _on_tree_right_click(self, event):
        item = event.GetItem()
        if self._locked:
            data = self.tree.GetItemData(item) if item.IsOk() and item != self.root else None
            if data and data["type"] == "cost":
                self.tree.SelectItem(item)
                menu = wx.Menu()
                calc_note = menu.Append(wx.ID_ANY, "Note de calcul tarifaire...")
                self.Bind(wx.EVT_MENU, lambda e: self._show_tariff_calculation_note(data["cost"], data["operation"]), calc_note)
                self.PopupMenu(menu)
                menu.Destroy()
            return
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
                menu.AppendSeparator()
                save_tpl = menu.Append(wx.ID_ANY, "Enregistrer comme modèle…")
                self.Bind(wx.EVT_MENU, self._on_save_operation_as_template, save_tpl)
                drift = menu.Append(wx.ID_ANY, "Recalculer l'écart au modèle")
                self.Bind(wx.EVT_MENU, self._on_recalc_template_drift, drift)
            
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
    
    # ------------------------------------------------------------------ outillage / sélection

    def _select_after_phase_change(self, op, cost=None):
        op_item = self._find_item_by_op(op, self.root)
        if not op_item or not op_item.IsOk():
            self._clear_properties()
            return
        if cost is not None:
            cost_item = self._find_item_by_cost(cost, op_item)
            if cost_item and cost_item.IsOk():
                self.tree.SelectItem(cost_item)
                self.tree.EnsureVisible(cost_item)
                return
        self.tree.SelectItem(op_item)
        self.tree.EnsureVisible(op_item)

    def _load_phase_row(self, data):
        """Facturation de l'outillage sélectionné (Décomposé uniquement).

        En Taux horaire l'outil est toujours refacturé séparément, jamais amorti :
        aucun choix à proposer.
        """
        self.phase_row.Freeze()
        self.phase_row_sizer.Clear(delete_windows=True)
        show_billing = bool(
            self.project and data and data["type"] == "cost"
            and data["cost"].cost_type == domain_cost.CostType.TOOLING
            and self.project.current_phase.kind == PhaseKind.SERIE)
        if show_billing:
            target = data["cost"]
            self.phase_row_sizer.Add(wx.StaticText(self.phase_row, label="Facturation de l'outillage :"), 0,
                                     wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
            version_mode = self.project.current_phase.effective_tooling_billing.value
            choices = [f"Selon la version ({version_mode})", ToolingBilling.REINVOICED.value, ToolingBilling.AMORTIZED.value]
            ch = wx.Choice(self.phase_row, choices=choices)
            ch.SetSelection(0 if target.tooling_billing is None else
                            1 if target.tooling_billing == ToolingBilling.REINVOICED else 2)
            ch.SetToolTip("Refacturé : bloc OUTILLAGE de l'offre, hors prix pièce.\n"
                          "Amorti : intégré au prix pièce, sur la durée de vie de l'outil.")
            ch.Bind(wx.EVT_CHOICE, lambda e, t=target, d=data: self._on_tooling_billing(e, t, d))
            self.phase_row_sizer.Add(ch, 0, wx.ALIGN_CENTER_VERTICAL)
        self.phase_row.Thaw()
        self.phase_row.Show(show_billing)
        self.phase_row.Layout()

    def _on_tooling_billing(self, event, target, data):
        idx = event.GetSelection()
        target.tooling_billing = (None, ToolingBilling.REINVOICED, ToolingBilling.AMORTIZED)[idx]
        self._refresh_operation_items(data["operation"])
        if self.on_operation_updated:
            self.on_operation_updated(None)

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
        lines.append(f"Projet: {self.project.display_name if self.project else '-'}")
        lines.append(f"Operation: {op.display_family or '-'} | {op.label}")
        lines.append(f"Poste de cout: {cost.name}")
        lines.append(f"Type de cout: {cost.cost_type.value}")
        lines.append(f"Conversion: {cost.conversion_type.value} x facteur {number(cost.conversion_factor if cost.conversion_factor else 1.0)}")
        lines.append(f"Marge appliquee: {number(cost.margin_rate)} %")
        lines.append("")

        if cost.cost_type == domain_cost.CostType.INTERNAL_OPERATION:
            lines.append("Parametres operation interne")
            lines.append(f"- Taux horaire: {euros(cost.hourly_rate)} / h")
            lines.append(f"- Temps fixe: {number(cost.fixed_time)} h")
            tp_suffix = " (Temps masqué)" if getattr(cost, 'is_temps_masque', False) else ""
            lines.append(f"- Temps par piece: {number(cost.per_piece_time)} h/pc{tp_suffix}")
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
                eff_per_piece = 0.0 if getattr(cost, 'is_temps_masque', False) else cost.per_piece_time
                total_time = cost.fixed_time + (eff_per_piece * qty)
                lines.append(f"- Temps total = {number(cost.fixed_time)} + ({number(eff_per_piece)} x {qty}) = {number(total_time)} h")
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
        if self._blocked():
            return
        if cost.cost_type != domain_cost.CostType.SUBCONTRACTING:
            return
        cost.is_active = True
        for other_cost in op.costs.values():
            if other_cost is not cost and other_cost.cost_type == domain_cost.CostType.SUBCONTRACTING:
                other_cost.is_active = False
        
        self._refresh_operation_items(op)
        # Also refresh property editor if it was showing this cost
        if self.current_data and self.current_data.get("cost") == cost:
            self.cost_editor.load_cost(cost, self.project)
            
        if self.on_operation_updated:
            self.on_operation_updated(None)

    def _on_move_op(self, direction):
        if self._blocked():
            return
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

    def _enforce_operation_constraints(self, op):
        return
