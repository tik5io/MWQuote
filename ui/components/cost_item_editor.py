# ui/components/cost_item_editor.py
import wx
import wx.grid as gridlib
import copy
import base64
import os
import tempfile
from domain.cost import CostItem, CostType, PricingType, PricingStructure, ConversionType, PricingTier
from domain.operation import SUBCONTRACTING_TYPOLOGY
from ui.components.document_list_panel import DocumentListPanel
from infrastructure.configuration import ConfigurationService
from infrastructure.logging_service import get_module_logger

logger = get_module_logger("CostItemEditor", "cost_item_editor.log")

class CostItemEditor(wx.Panel):
    """Component for editing a CostItem and showing its real-time calculations."""

    def __init__(self, parent):
        super().__init__(parent)
        self.cost = None
        self.project = None
        self.on_changed = None # Callback to notify parent (passed a temp CostItem)
        self._updating_time = False
        self.config_service = ConfigurationService()
        self.doc_list = None
        
        # Debounce timer for UI refresh
        self._update_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer_refresh, self._update_timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        
        self._build_ui()

    def _on_destroy(self, event):
        # Prevent delayed timer callbacks from running during panel teardown.
        if event.GetEventObject() is self and hasattr(self, "_update_timer") and self._update_timer:
            self._update_timer.Stop()
        event.Skip()

    @staticmethod
    def get_analysis_preview_metrics(cost, qty):
        """Return the cost and sale price metrics used by the real-time analysis panel."""
        from domain.calculator import Calculator

        if not cost or qty <= 0:
            return {
                "cost_per_piece": 0.0,
                "sale_price_per_piece": 0.0,
                "sale_price_total": 0.0,
                "batch_supplier_cost": 0.0,
                "quote_qty_ordered": 0.0,
                "margin_rate": getattr(cost, "margin_rate", 0.0),
            }

        res = Calculator.calculate_item(cost, qty)
        return {
            "cost_per_piece": res.unit_cost_converted,
            "sale_price_per_piece": res.unit_sale_price,
            "sale_price_total": res.unit_sale_price * qty,
            "batch_supplier_cost": res.batch_supplier_cost,
            "quote_qty_ordered": res.quote_qty_ordered,
            "margin_rate": getattr(cost, "margin_rate", 0.0),
        }

    def _ctrl_get_value(self, attr_name, default="", strip=False):
        """Safely read a wx control value; returns default if control is absent or deleted."""
        ctrl = getattr(self, attr_name, None)
        if not ctrl:
            return default
        try:
            value = ctrl.GetValue()
        except RuntimeError:
            return default
        if strip and isinstance(value, str):
            return value.strip()
        return value

    def _ctrl_get_selection(self, attr_name, default=""):
        """Safely read a wx choice selection; returns default if control is absent or deleted."""
        ctrl = getattr(self, attr_name, None)
        if not ctrl:
            return default
        try:
            return ctrl.GetStringSelection()
        except RuntimeError:
            return default

    def _ctrl_set_label(self, attr_name, label):
        """Safely set a wx static text label; returns False if control is absent or deleted."""
        ctrl = getattr(self, attr_name, None)
        if not ctrl:
            return False
        try:
            ctrl.SetLabel(label)
            return True
        except RuntimeError:
            return False

    def _build_ui(self):
        # Main layout is HORIZONTAL
        self.main_h_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # LEFT COLUMN: Inputs (Scrolled for small screens)
        self.left_column = wx.Panel(self)      # le défilement est assuré par le panneau parent
        self.left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 1. Base Properties (Name, Type)
        self.base_grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=8)
        self.base_grid.AddGrowableCol(1, 1)
        
        self.base_grid.Add(wx.StaticText(self.left_column, label="Désignation:"))
        self.prop_name = wx.TextCtrl(self.left_column)
        self.prop_name.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
        self.base_grid.Add(self.prop_name, 1, wx.EXPAND)

        # Commentaire méthode : en tête, juste sous la désignation (valable pour tous les types)
        self.lbl_comment = wx.StaticText(self.left_column, label="Commentaire méthode:")
        self.base_grid.Add(self.lbl_comment, 0, wx.TOP, 3)
        self.prop_comment = wx.TextCtrl(self.left_column, style=wx.TE_MULTILINE | wx.TE_WORDWRAP, size=(-1, 72))
        self.prop_comment.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
        self.base_grid.Add(self.prop_comment, 1, wx.EXPAND)

        # Marge commerciale : rang 2 (masquée pour un outillage, refacturé sans marge)
        self.lbl_margin = wx.StaticText(self.left_column, label="Marge commerciale (%):")
        self.base_grid.Add(self.lbl_margin, 0, wx.ALIGN_CENTER_VERTICAL)
        self.prop_margin_rate = wx.TextCtrl(self.left_column, size=(90, -1))
        self.prop_margin_rate.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
        self.base_grid.Add(self.prop_margin_rate, 0)
        
        # Le type de coût n'est plus choisi par l'utilisateur : il découle de
        # l'opération (Interne → temps, Sous-traitance → achat) et du bouton
        # « + Outillage ». Le rendu ci-dessous s'adapte à cost.cost_type.

        # New: Active Checkbox (for Sous-traitance)
        self.lbl_active = wx.StaticText(self.left_column, label="État:")
        self.base_grid.Add(self.lbl_active)
        self.prop_active = wx.CheckBox(self.left_column, label="Utiliser cette offre pour le chiffrage")
        self.prop_active.Bind(wx.EVT_CHECKBOX, lambda e: self.notify_change())
        self.base_grid.Add(self.prop_active, 1, wx.EXPAND)
        
        self.left_sizer.Add(self.base_grid, 0, wx.EXPAND | wx.ALL, 10)
        
        # 2. Dynamic fields container
        self.dynamic_sizer = wx.BoxSizer(wx.VERTICAL)
        self.left_sizer.Add(self.dynamic_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        self.left_column.SetSizer(self.left_sizer)
        self.main_h_sizer.Add(self.left_column, 0, wx.EXPAND)
        
        # Prix de l'étape, décliné par quantité (même présentation que le panneau Gamme)
        from ui.components.line_price_panel import LinePricePanel
        self.main_h_sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.price_panel = LinePricePanel(self)
        self.main_h_sizer.Add(self.price_panel, 1, wx.EXPAND | wx.TOP, 6)
        
        self.SetSizer(self.main_h_sizer)

    def load_cost(self, cost: CostItem, project):
        self._is_loading = True
        self._update_timer.Stop() # Prevent pending updates from previous cost
        try:
            logger.info(f"load_cost | name={getattr(cost, 'name', '?')} type={getattr(cost, 'cost_type', '?')}")
            self.cost = cost
            self.project = project
            self.prop_name.ChangeValue(cost.name or "")
            self.prop_active.SetValue(cost.is_active)
            self.prop_comment.ChangeValue(cost.comment or "")
            self.prop_margin_rate.ChangeValue(f"{cost.margin_rate:.1f}")
            is_tooling = cost.cost_type == CostType.TOOLING
            self.lbl_margin.Show(not is_tooling)
            self.prop_margin_rate.Show(not is_tooling)
            
            # Show/hide active checkbox based on context (provided by parent via project if needed, 
            # or just always show if SUBCONTRACTING)
            from domain.operation import SUBCONTRACTING_TYPOLOGY
            # We assume the parent gives us a hint about the operation typology
            # For now, let's keep it simple: show if cost_type is SUBCONTRACTING
            self.prop_active.Show(cost.cost_type == CostType.SUBCONTRACTING)
            self.lbl_active.Show(cost.cost_type == CostType.SUBCONTRACTING)
            self.prop_active.GetContainingSizer().Layout()
            
            self._refresh_dynamic_fields()
            self._refresh_price_panel(cost)
            self.main_h_sizer.Layout()
        finally:
            self._is_loading = False

    def _owner_op(self):
        """Opération qui contient la ligne éditée (None si introuvable)."""
        for op in getattr(self.project, "operations", []) or []:
            if any(c is self.cost for c in op.costs.values()):
                return op
        return None

    def _refresh_dynamic_fields(self):
        self._update_timer.Stop()
        self.label_conso = None
        # We want to keep some components alive if possible (e.g. DocListPanel)
        # to avoid recursive re-creation loops during layout events.
        saved_doc_list = self.doc_list
        if saved_doc_list:
            saved_doc_list.Reparent(wx.Panel(self)) # Temporarily move it out
            saved_doc_list.Hide()
            self.doc_list = None 

        self.dynamic_sizer.Clear(True)
        cost = self.cost
        
        # Helper to create a grid in a labeled box
        def create_box_grid(label):
            box = wx.StaticBox(self.left_column, label=label) # Parent is left_column
            box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
            grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=5)
            grid.AddGrowableCol(1, 1)
            box_sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 5)
            return box_sizer, grid

        match cost.cost_type:
            case CostType.MATERIAL | CostType.SUBCONTRACTING:
                # SECTION 1: OFFRE FOURNISSEUR
                offer_sizer, offer_grid = create_box_grid("OFFRE FOURNISSEUR")
                
                if cost.cost_type == CostType.SUBCONTRACTING:
                    offer_grid.Add(wx.StaticText(self.left_column, label="Réf. Offre:"), 0, wx.ALIGN_CENTER_VERTICAL)
                    self.prop_supplier_quote_ref = wx.TextCtrl(self.left_column, value=cost.supplier_quote_ref or "")
                    self.prop_supplier_quote_ref.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                    offer_grid.Add(self.prop_supplier_quote_ref, 1, wx.EXPAND)
                    
                    if not saved_doc_list:
                        self.doc_list = DocumentListPanel(self.left_column, label="Offres Fournisseur (PDF) :",
                                                          project_name_callback=lambda: getattr(getattr(self, 'project', None), 'reference', None) or "")
                    else:
                        self.doc_list = saved_doc_list
                        self.doc_list.Reparent(self.left_column)
                        self.doc_list.Show()
                        
                    self.doc_list.load_documents(cost.documents)
                    self.doc_list.on_changed = self.notify_change
                    offer_sizer.Add(self.doc_list, 0, wx.EXPAND | wx.TOP, 10)
                elif saved_doc_list:
                    saved_doc_list.Destroy() # Finally destroy it if not needed

                offer_grid.Add(wx.StaticText(self.left_column, label="Unité devis:"), 0, wx.ALIGN_CENTER_VERTICAL)
                self.prop_unit = wx.TextCtrl(self.left_column, value=cost.pricing.unit)
                self.prop_unit.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                offer_grid.Add(self.prop_unit, 1, wx.EXPAND)

                offer_grid.Add(wx.StaticText(self.left_column, label="Type Tarification:"), 0, wx.ALIGN_CENTER_VERTICAL)
                self.prop_pricing_type = wx.Choice(self.left_column, choices=[pt.value for pt in PricingType])
                self.prop_pricing_type.SetStringSelection(cost.pricing.pricing_type.value)
                self.prop_pricing_type.Bind(wx.EVT_CHOICE, self._on_pricing_type_changed)
                offer_grid.Add(self.prop_pricing_type, 1, wx.EXPAND)

                if cost.pricing.pricing_type in [PricingType.PER_UNIT, PricingType.TIERED]:
                    offer_grid.Add(wx.StaticText(self.left_column, label="Frais fixes (€):"), 0, wx.ALIGN_CENTER_VERTICAL)
                    self.prop_fixed_price = wx.TextCtrl(self.left_column, value=f"{cost.pricing.fixed_price:.2f}")
                    self.prop_fixed_price.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                    offer_grid.Add(self.prop_fixed_price, 1, wx.EXPAND)

                if cost.pricing.pricing_type == PricingType.PER_UNIT:
                    offer_grid.Add(wx.StaticText(self.left_column, label="Prix unitaire (€):"), 0, wx.ALIGN_CENTER_VERTICAL)
                    self.prop_unit_price = wx.TextCtrl(self.left_column, value=f"{cost.pricing.unit_price:.2f}")
                    self.prop_unit_price.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                    offer_grid.Add(self.prop_unit_price, 1, wx.EXPAND)
                elif cost.pricing.pricing_type == PricingType.TIERED:
                    offer_grid.Add(wx.StaticText(self.left_column, label="Échelons Q/P:"), 0, wx.ALIGN_CENTER_VERTICAL)
                    btn = wx.Button(self.left_column, label="Gérer les échelons...")
                    btn.Bind(wx.EVT_BUTTON, self._on_manage_tiers)
                    offer_grid.Add(btn, 1, wx.EXPAND)
                
                self.dynamic_sizer.Add(offer_sizer, 0, wx.EXPAND | wx.BOTTOM, 10)

                # (L'outillage fournisseur et ses pièces incluses se déclarent désormais
                # dans une ligne « Nouvel outillage » de l'opération.)

                # SECTION 2: CONSOMMATION PRODUCTION
                production_sizer, production_grid = create_box_grid("CONSOMMATION PRODUCTION")
                unit = cost.pricing.unit or "unité"
                if cost.quantity_per_piece_is_inverse:
                    label_conso = f"Consommation (pièce/{unit}):"
                else:
                    label_conso = f"Consommation ({unit}/pièce):"
                self.label_conso = wx.StaticText(self.left_column, label=label_conso)
                production_grid.Add(self.label_conso, 0, wx.ALIGN_CENTER_VERTICAL)
                self.prop_qty_per_piece = wx.TextCtrl(self.left_column, value=f"{cost.quantity_per_piece or 1.0:g}")
                self.prop_qty_per_piece.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                production_grid.Add(self.prop_qty_per_piece, 1, wx.EXPAND)
                
                self.prop_qty_inverse = wx.CheckBox(self.left_column, label="Interpréter en pièces/unité")
                self.prop_qty_inverse.SetValue(bool(cost.quantity_per_piece_is_inverse))
                self.prop_qty_inverse.Bind(wx.EVT_CHECKBOX, lambda e: self.notify_change())
                production_grid.Add(self.prop_qty_inverse, 0, wx.ALIGN_CENTER_VERTICAL)
                production_grid.Add(wx.StaticText(self.left_column, label=""), 1, wx.EXPAND)
                self.dynamic_sizer.Add(production_sizer, 0, wx.EXPAND | wx.BOTTOM, 10)

            case CostType.INTERNAL_OPERATION:
                has_serie = self._project_has_serie_phase()
                op_sizer, op_grid = create_box_grid(
                    "PROTO / LOT — temps passé" if has_serie else "DÉTAILS OPÉRATION")
                op_grid.Add(wx.StaticText(self.left_column, label="Taux horaire (€/h):"), 0, wx.ALIGN_CENTER_VERTICAL)
                self.prop_internal_rate = wx.TextCtrl(self.left_column, value=f"{cost.hourly_rate:.2f}")
                self.prop_internal_rate.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                op_grid.Add(self.prop_internal_rate, 1, wx.EXPAND)
                self._add_detailed_time_row(op_grid, "Temps fixe:", cost.fixed_time, "fixed")
                self._add_detailed_time_row(op_grid, "Temps/pièce:", cost.per_piece_time, "piece")
                
                # Checkbox for Temps masqué
                self.prop_temps_masque = wx.CheckBox(self.left_column, label="Temps masqué (neutralise le temps/pièce)")
                self.prop_temps_masque.SetValue(getattr(cost, 'is_temps_masque', False))
                self.prop_temps_masque.Bind(wx.EVT_CHECKBOX, self._on_temps_masque_changed)
                op_grid.Add(self.prop_temps_masque, 0, wx.ALIGN_CENTER_VERTICAL)
                op_grid.Add(wx.StaticText(self.left_column, label=""), 1, wx.EXPAND)
                
                is_masked = getattr(cost, 'is_temps_masque', False)
                self.prop_piece_h.Enable(not is_masked)
                self.prop_piece_m.Enable(not is_masked)
                self.prop_piece_s.Enable(not is_masked)

                self.dynamic_sizer.Add(op_sizer, 0, wx.EXPAND | wx.BOTTOM, 10)

                # Valorisation SÉRIE de la même étape (héritée du Proto tant qu'elle n'est pas saisie)
                self._serie_fields = {}
                if has_serie:
                    serie_sizer, serie_grid = create_box_grid("SÉRIE — temps de cycle (↺ = hérité du Proto)")
                    for key, label, unit in self.SERIE_FIELDS:
                        self._add_serie_field(serie_grid, cost, key, label, unit)
                    self.dynamic_sizer.Add(serie_sizer, 0, wx.EXPAND | wx.BOTTOM, 10)

            case CostType.TOOLING:
                if saved_doc_list:
                    saved_doc_list.Destroy()
                tool_sizer, tool_grid = create_box_grid("OUTILLAGE")
                if not cost.pricing:
                    cost.pricing = PricingStructure(PricingType.PER_UNIT)
                tool_grid.Add(wx.StaticText(self.left_column, label="Montant outillage (€):"), 0, wx.ALIGN_CENTER_VERTICAL)
                self.prop_tool_price = wx.TextCtrl(self.left_column, value=f"{cost.pricing.fixed_price:.2f}")
                self.prop_tool_price.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                tool_grid.Add(self.prop_tool_price, 1, wx.EXPAND)

                # Pièces fournies avec l'outil : gratuites (part achat à 0) jusqu'à ce
                # nombre, puis prix pièce / échelon de l'offre au-delà.
                tool_grid.Add(wx.StaticText(self.left_column, label="Pièces fournies avec l'outil:"), 0, wx.ALIGN_CENTER_VERTICAL)
                self.prop_tool_included = wx.TextCtrl(self.left_column, value=f"{int(cost.tooling_included_pieces or 0)}")
                self.prop_tool_included.SetToolTip(
                    "Pièces livrées avec l'outillage (mise au point, proto) : comprises dans son prix.\n"
                    "Jusqu'à ce nombre la part achat de l'opération est à 0 ; au-delà, prix pièce / échelon normal.")
                self.prop_tool_included.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                tool_grid.Add(self.prop_tool_included, 1, wx.EXPAND)

                # Rattachement à une offre (opération Sous-traitance multi-offres)
                self._tool_offer_keys = []
                owner = self._owner_op()
                if owner is not None and owner.typology == SUBCONTRACTING_TYPOLOGY:
                    self._tool_offer_keys = [k for k, c in owner.costs.items()
                                             if c.cost_type == CostType.SUBCONTRACTING]
                    tool_grid.Add(wx.StaticText(self.left_column, label="Rattaché à:"), 0, wx.ALIGN_CENTER_VERTICAL)
                    self.prop_tool_offer = wx.Choice(self.left_column,
                                                     choices=["Toute l'opération"] + self._tool_offer_keys)
                    sel = (self._tool_offer_keys.index(cost.linked_offer) + 1
                           if cost.linked_offer in self._tool_offer_keys else 0)
                    self.prop_tool_offer.SetSelection(sel)
                    self.prop_tool_offer.SetToolTip(
                        "Un outillage rattaché à une offre n'est facturé (et ses pièces gratuites\n"
                        "ne comptent) que tant que cette offre est retenue.")
                    self.prop_tool_offer.Bind(wx.EVT_CHOICE, lambda e: self.notify_change())
                    tool_grid.Add(self.prop_tool_offer, 1, wx.EXPAND)

                # Détail ligne à ligne : le montant de l'outillage = somme des lignes
                tool_grid.Add(wx.StaticText(self.left_column, label="Détail :"), 0, wx.TOP, 5)
                tool_grid.Add(self._build_tooling_lines_editor(cost), 1, wx.EXPAND | wx.TOP, 5)


                tool_grid.Add(wx.StaticText(self.left_column, label="Commentaire Client (devis):"), 0, wx.TOP, 5)
                self.prop_client_comment = wx.TextCtrl(self.left_column, value=cost.client_comment or "", style=wx.TE_MULTILINE | wx.TE_WORDWRAP, size=(-1, 90))
                self.prop_client_comment.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                tool_grid.Add(self.prop_client_comment, 1, wx.EXPAND | wx.TOP, 5)
                self.dynamic_sizer.Add(tool_sizer, 0, wx.EXPAND)

        # SECTION 3: MÉTHODE & PARAMÈTRES COMMERCIAUX (non outillage)
        if cost.cost_type != CostType.TOOLING:
            # 3a. Box: ORGANISATION / MÉTHODE
            method_sizer, method_grid = create_box_grid("ORGANISATION / MÉTHODE")
            
            method_grid.Add(wx.StaticText(self.left_column, label="Mode d'exécution :"), 0, wx.ALIGN_CENTER_VERTICAL)
            choices_ui = ["Série (Multiplier)", "Parallèle (Diviser)"]
            self.prop_conv_type = wx.Choice(self.left_column, choices=choices_ui)
            sel_str = "Série (Multiplier)" if cost.conversion_type == ConversionType.MULTIPLY else "Parallèle (Diviser)"
            self.prop_conv_type.SetStringSelection(sel_str)
            self.prop_conv_type.Bind(wx.EVT_CHOICE, lambda e: self.notify_change())
            method_grid.Add(self.prop_conv_type, 1, wx.EXPAND)

            method_grid.Add(wx.StaticText(self.left_column, label="Facteur multiplicateur/diviseur :"), 0, wx.ALIGN_CENTER_VERTICAL)
            self.prop_conv_factor = wx.TextCtrl(self.left_column, value=f"{cost.conversion_factor:.4f}")
            self.prop_conv_factor.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
            method_grid.Add(self.prop_conv_factor, 1, wx.EXPAND)


            self.dynamic_sizer.Add(method_sizer, 0, wx.EXPAND | wx.BOTTOM, 10)

            # (La marge commerciale est en tête du panneau, sous le commentaire méthode.)
        
        self.left_sizer.Layout()
        self.main_h_sizer.Layout()
        self.notify_change()

    # ------------------------------------------------------------------ détail outillage

    TOOL_COLS = [("Désignation", 170), ("Qté", 55), ("Unité", 60), ("PU (€)", 75), ("Total (€)", 85)]

    def _build_tooling_lines_editor(self, cost):
        panel = wx.Panel(self.left_column)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.tool_lines_grid = gridlib.Grid(panel)
        g = self.tool_lines_grid
        g.CreateGrid(0, len(self.TOOL_COLS))
        g.SetRowLabelSize(0)
        for col, (label, width) in enumerate(self.TOOL_COLS):
            g.SetColLabelValue(col, label)
            g.SetColSize(col, width)
        for line in cost.tooling_lines:
            self._append_tool_line_row(line.label, line.quantity, line.unit, line.unit_price)
        g.SetMinSize((-1, 130))
        g.Bind(gridlib.EVT_GRID_CELL_CHANGED, self._on_tool_line_changed)
        sizer.Add(g, 1, wx.EXPAND)

        bar = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(panel, label="+ Ligne", size=(70, 24))
        add_btn.Bind(wx.EVT_BUTTON, self._on_add_tool_line)
        del_btn = wx.Button(panel, label="Supprimer", size=(80, 24))
        del_btn.Bind(wx.EVT_BUTTON, self._on_del_tool_line)
        bar.Add(add_btn, 0, wx.RIGHT, 4)
        bar.Add(del_btn, 0, wx.RIGHT, 12)
        self.lbl_tool_lines_total = wx.StaticText(panel, label="")
        self.lbl_tool_lines_total.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        bar.Add(self.lbl_tool_lines_total, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(bar, 0, wx.TOP, 4)
        panel.SetSizer(sizer)
        self._refresh_tool_lines_total(notify=False)
        return panel

    def _append_tool_line_row(self, label="", quantity=1.0, unit="", unit_price=0.0):
        g = self.tool_lines_grid
        row = g.GetNumberRows()
        g.AppendRows(1)
        g.SetCellValue(row, 0, label or "")
        g.SetCellValue(row, 1, f"{quantity:g}")
        g.SetCellValue(row, 2, unit or "")
        g.SetCellValue(row, 3, f"{unit_price:.2f}")
        g.SetReadOnly(row, 4, True)
        g.SetCellBackgroundColour(row, 4, wx.Colour(240, 240, 240))
        for col in (1, 3, 4):
            g.SetCellAlignment(row, col, wx.ALIGN_RIGHT, wx.ALIGN_CENTER)

    def _read_tool_lines(self):
        """Lignes saisies (les lignes entièrement vides sont ignorées)."""
        from domain.cost import ToolingLine
        g = getattr(self, "tool_lines_grid", None)
        lines = []
        if not g:
            return lines
        try:
            n = g.GetNumberRows()
        except RuntimeError:
            return lines

        def num(text, default):
            try:
                return float(text.replace(",", ".").replace(" ", "") or default)
            except ValueError:
                return default

        for row in range(n):
            label = g.GetCellValue(row, 0).strip()
            qty = num(g.GetCellValue(row, 1), 1.0)
            unit = g.GetCellValue(row, 2).strip()
            pu = num(g.GetCellValue(row, 3), 0.0)
            if not label and pu == 0.0:
                continue
            lines.append(ToolingLine(label=label, quantity=qty, unit=unit, unit_price=pu))
        return lines

    def _refresh_tool_lines_total(self, notify=True):
        g = self.tool_lines_grid
        lines_total = 0.0
        for row in range(g.GetNumberRows()):
            try:
                qty = float(g.GetCellValue(row, 1).replace(",", ".").replace(" ", "") or 0)
                pu = float(g.GetCellValue(row, 3).replace(",", ".").replace(" ", "") or 0)
            except ValueError:
                qty, pu = 0.0, 0.0
            g.SetCellValue(row, 4, f"{qty * pu:,.2f}".replace(",", " "))
            lines_total += qty * pu
        has_lines = bool(self._read_tool_lines())
        # Avec un détail, le montant est calculé : champ en lecture seule
        self.prop_tool_price.SetEditable(not has_lines)
        self.prop_tool_price.SetBackgroundColour(wx.Colour(240, 240, 240) if has_lines else wx.NullColour)
        if has_lines:
            self.prop_tool_price.ChangeValue(f"{lines_total:.2f}")
            self.lbl_tool_lines_total.SetLabel(f"Total : {lines_total:,.2f} €".replace(",", " "))
        else:
            self.lbl_tool_lines_total.SetLabel("Sans détail : montant saisi directement")
        self.prop_tool_price.Refresh()
        if notify:
            self.notify_change()

    def _on_tool_line_changed(self, event):
        self._refresh_tool_lines_total()
        event.Skip()

    def _on_add_tool_line(self, event):
        g = self.tool_lines_grid
        # Premier détail sur un outillage déjà chiffré : conserver le montant saisi
        if g.GetNumberRows() == 0:
            try:
                current = float(self.prop_tool_price.GetValue().replace(",", ".") or 0)
            except ValueError:
                current = 0.0
            if current > 0:
                self._append_tool_line_row("Montant saisi", 1.0, "forfait", current)
        self._append_tool_line_row()
        self._refresh_tool_lines_total()
        row = g.GetNumberRows() - 1
        g.SetGridCursor(row, 0)
        g.MakeCellVisible(row, 0)
        self.left_sizer.Layout()

    def _on_del_tool_line(self, event):
        g = self.tool_lines_grid
        rows = sorted(set(g.GetSelectedRows()) | {g.GetGridCursorRow()}, reverse=True)
        for row in rows:
            if 0 <= row < g.GetNumberRows():
                g.DeleteRows(row, 1)
        self._refresh_tool_lines_total()

    # ------------------------------------------------------------------ bloc SÉRIE

    # (attribut CostItem, libellé, unité)
    SERIE_FIELDS = [
        ("serie_cycle_time_s", "Temps de cycle :", "s"),
        ("serie_pieces_per_cycle", "Pièces simultanées :", "pcs / cycle"),
        ("serie_setup_h", "Réglage / campagne :", "h"),
        ("serie_hourly_rate", "Taux horaire série :", "€/h"),
    ]

    def _project_has_serie_phase(self):
        return any(getattr(ph, "is_serie", False) for ph in getattr(getattr(self, "project", None), "phases", []) or [])

    @staticmethod
    def _inherited_serie_value(cost, key):
        return {
            "serie_cycle_time_s": cost.inherited_serie_cycle_time_s,
            "serie_pieces_per_cycle": cost.inherited_serie_pieces_per_cycle,
            "serie_setup_h": cost.inherited_serie_setup_h,
            "serie_hourly_rate": lambda: cost.hourly_rate or 0.0,
        }[key]()

    def _add_serie_field(self, grid, cost, key, label, unit):
        grid.Add(wx.StaticText(self.left_column, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        ctrl = wx.TextCtrl(self.left_column, size=(90, -1))
        row.Add(ctrl, 0, wx.RIGHT, 4)
        row.Add(wx.StaticText(self.left_column, label=unit), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        state = wx.StaticText(self.left_column, label="")
        row.Add(state, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        reset = wx.Button(self.left_column, label="↺", size=(28, 22))
        reset.SetToolTip("Revenir à la valeur héritée du Proto")
        row.Add(reset, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(row, 1, wx.EXPAND)
        value = getattr(cost, key)
        self._serie_fields[key] = {"ctrl": ctrl, "state": state, "reset": reset, "overridden": value is not None}
        ctrl.Bind(wx.EVT_TEXT, lambda e, k=key: self._on_serie_field_edited(k))
        reset.Bind(wx.EVT_BUTTON, lambda e, k=key: self._on_serie_field_reset(k))
        self._show_serie_field(key, value if value is not None else self._inherited_serie_value(cost, key))

    def _show_serie_field(self, key, value):
        f = self._serie_fields[key]
        f["ctrl"].ChangeValue(f"{value:g}" if value is not None else "")
        inherited = not f["overridden"]
        f["ctrl"].SetForegroundColour(wx.Colour(140, 140, 140) if inherited else wx.BLACK)
        font = f["ctrl"].GetFont()
        font.SetStyle(wx.FONTSTYLE_ITALIC if inherited else wx.FONTSTYLE_NORMAL)
        f["ctrl"].SetFont(font)
        f["state"].SetLabel("↺ hérité" if inherited else "saisi série")
        f["state"].SetForegroundColour(wx.Colour(140, 140, 140) if inherited else wx.Colour(30, 110, 30))
        f["reset"].Enable(not inherited)
        f["ctrl"].Refresh()

    def _on_serie_field_edited(self, key):
        if getattr(self, "_is_loading", False):
            return
        f = self._serie_fields[key]
        if not f["overridden"]:
            f["overridden"] = True
            self._show_serie_field(key, self._read_serie_field(key))
        self.notify_change()

    def _on_serie_field_reset(self, key):
        self._serie_fields[key]["overridden"] = False
        self._show_serie_field(key, self._inherited_serie_value(self.cost, key))
        self.notify_change()

    def _read_serie_field(self, key):
        try:
            return float(self._serie_fields[key]["ctrl"].GetValue().replace(",", ".").replace(" ", ""))
        except (ValueError, RuntimeError):
            return None

    def _refresh_serie_inherited(self, temp_cost):
        """Les valeurs héritées suivent la saisie Proto en direct."""
        for key, f in getattr(self, "_serie_fields", {}).items():
            try:
                if not f["overridden"]:
                    self._show_serie_field(key, self._inherited_serie_value(temp_cost, key))
            except RuntimeError:
                pass

    def _add_detailed_time_row(self, grid, label, initial_hours, prefix):
        grid.Add(wx.StaticText(self.left_column, label=label))
        row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        h_ctrl = wx.TextCtrl(self.left_column, value=f"{initial_hours:.4f}", size=(60, -1))
        setattr(self, f"prop_{prefix}_h", h_ctrl)
        row_sizer.Add(h_ctrl, 0, wx.RIGHT, 2)
        row_sizer.Add(wx.StaticText(self.left_column, label="h"), 0, wx.RIGHT, 5)
        
        m_ctrl = wx.TextCtrl(self.left_column, value=f"{initial_hours*60:.2f}", size=(60, -1))
        setattr(self, f"prop_{prefix}_m", m_ctrl)
        row_sizer.Add(m_ctrl, 0, wx.RIGHT, 2)
        row_sizer.Add(wx.StaticText(self.left_column, label="m"), 0, wx.RIGHT, 5)
        
        s_ctrl = wx.TextCtrl(self.left_column, value=f"{int(round(initial_hours*3600))}", size=(60, -1))
        setattr(self, f"prop_{prefix}_s", s_ctrl)
        row_sizer.Add(s_ctrl, 0, wx.RIGHT, 2)
        row_sizer.Add(wx.StaticText(self.left_column, label="s"), 0, wx.RIGHT, 5)
        
        grid.Add(row_sizer, 1, wx.EXPAND)
        
        h_ctrl.Bind(wx.EVT_TEXT, lambda e: self._on_time_entry_changed(prefix, 'h'))
        m_ctrl.Bind(wx.EVT_TEXT, lambda e: self._on_time_entry_changed(prefix, 'm'))
        s_ctrl.Bind(wx.EVT_TEXT, lambda e: self._on_time_entry_changed(prefix, 's'))

    def _on_time_entry_changed(self, prefix, source_unit):
        if hasattr(self, "_is_loading") and self._is_loading: return
        if self._updating_time: return
        self._updating_time = True
        try:
            ctrl = getattr(self, f"prop_{prefix}_{source_unit}")
            val_str = ctrl.GetValue().replace(',', '.')
            val = float(val_str or 0)
            hours = val if source_unit == 'h' else val/60.0 if source_unit == 'm' else val/3600.0
            
            # Update others only if they differ to avoid cursor reset issues
            if source_unit != 'h': getattr(self, f"prop_{prefix}_h").ChangeValue(f"{hours:.4f}")
            if source_unit != 'm': getattr(self, f"prop_{prefix}_m").ChangeValue(f"{hours*60:.2f}")
            if source_unit != 's': getattr(self, f"prop_{prefix}_s").ChangeValue(f"{int(round(hours*3600))}")
            self.notify_change()
        except ValueError: pass
        finally: self._updating_time = False

    def _on_pricing_type_changed(self, event):
        if hasattr(self, "_is_loading") and self._is_loading: return
        new_val = self.prop_pricing_type.GetStringSelection()
        for pt in PricingType:
            if pt.value == new_val:
                self.cost.pricing.pricing_type = pt
                break
        self._refresh_dynamic_fields()

    def apply_changes(self):
        """Save UI values back to the cost object."""
        if not self.cost: return
        
        def safe_float(val_str, default=0.0):
            try:
                return float(val_str.replace(',', '.') or default)
            except ValueError:
                return default

        try:
            logger.debug(f"apply_changes start | name={getattr(self.cost, 'name', '?')}")
            self.cost.name = self.prop_name.GetValue().strip()
            if self.cost.cost_type in [CostType.MATERIAL, CostType.SUBCONTRACTING]:
                # Save shared unit first
                self.cost.pricing.unit = self.prop_unit.GetValue().strip()

                if self.cost.pricing.pricing_type in [PricingType.PER_UNIT, PricingType.TIERED]:
                    self.cost.pricing.fixed_price = safe_float(self.prop_fixed_price.GetValue())
                if self.cost.pricing.pricing_type == PricingType.PER_UNIT:
                    self.cost.pricing.unit_price = safe_float(self.prop_unit_price.GetValue())
                if hasattr(self, 'prop_qty_per_piece'):
                    self.cost.quantity_per_piece = safe_float(self.prop_qty_per_piece.GetValue(), 1.0)
                if hasattr(self, 'prop_qty_inverse'):
                    self.cost.quantity_per_piece_is_inverse = self.prop_qty_inverse.GetValue()
                # Save supplier quote reference for SUBCONTRACTING
                if self.cost.cost_type == CostType.SUBCONTRACTING and hasattr(self, 'prop_supplier_quote_ref'):
                    self.cost.supplier_quote_ref = self.prop_supplier_quote_ref.GetValue()
            elif self.cost.cost_type == CostType.INTERNAL_OPERATION:
                if hasattr(self, 'prop_internal_rate'):
                    self.cost.hourly_rate = safe_float(self.prop_internal_rate.GetValue())
                if hasattr(self, 'prop_fixed_h'):
                    self.cost.fixed_time = safe_float(self.prop_fixed_h.GetValue())
                if hasattr(self, 'prop_piece_h'):
                    self.cost.per_piece_time = safe_float(self.prop_piece_h.GetValue())
                if hasattr(self, 'prop_temps_masque'):
                    self.cost.is_temps_masque = self.prop_temps_masque.GetValue()
                # Bloc SÉRIE : valeur saisie, ou None = héritée du Proto
                for key, f in getattr(self, "_serie_fields", {}).items():
                    value = self._read_serie_field(key) if f["overridden"] else None
                    if key == "serie_pieces_per_cycle" and value is not None and value <= 0:
                        value = None
                    setattr(self.cost, key, value)
                
                # Clear pricing structure to avoid conflict in Calculator
                if self.cost.pricing:
                    self.cost.pricing.unit_price = 0
                    self.cost.pricing.fixed_price = 0
                    self.cost.pricing.tiers = []
            elif self.cost.cost_type == CostType.TOOLING:
                if not self.cost.pricing:
                    self.cost.pricing = PricingStructure(PricingType.PER_UNIT)
                self.cost.pricing.fixed_price = safe_float(self.prop_tool_price.GetValue())
                if hasattr(self, 'tool_lines_grid'):
                    self.cost.tooling_lines = self._read_tool_lines()
                    self.cost.apply_tooling_lines()
                self.cost.pricing.unit_price = 0.0
                self.cost.pricing.tiers = []
                self.cost.pricing.unit = "forfait"
                if hasattr(self, 'prop_tool_included'):
                    self.cost.tooling_included_pieces = max(int(safe_float(self.prop_tool_included.GetValue())), 0)
                if hasattr(self, 'prop_tool_offer'):
                    sel = self.prop_tool_offer.GetSelection()
                    self.cost.linked_offer = self._tool_offer_keys[sel - 1] if sel > 0 else None
                self.cost.comment = self.prop_comment.GetValue()
                if hasattr(self, 'prop_client_comment'):
                    self.cost.client_comment = self.prop_client_comment.GetValue()
                self.cost.margin_rate = 0.0
                self.cost.conversion_factor = 1.0
                self.cost.conversion_type = ConversionType.MULTIPLY
            
            if self.cost.cost_type != CostType.TOOLING:
                self.cost.conversion_factor = safe_float(self.prop_conv_factor.GetValue(), 1.0)
                self.cost.margin_rate = safe_float(self.prop_margin_rate.GetValue())
                self.cost.comment = self.prop_comment.GetValue()
                cv_val = self.prop_conv_type.GetStringSelection()
                self.cost.conversion_type = ConversionType.MULTIPLY if "Série" in cv_val else ConversionType.DIVIDE
            self.cost.is_active = self.prop_active.GetValue()
            logger.debug(
                f"apply_changes done | name={self.cost.name} type={self.cost.cost_type} "
                f"conv={self.cost.conversion_type.value} factor={self.cost.conversion_factor} "
                f"margin={self.cost.margin_rate}"
            )
            return True
        except Exception:
            logger.exception("apply_changes failed")
            return False

    def notify_change(self):
        if getattr(self, "_is_loading", False) or not self.cost or not self.on_changed: return
        # Debounce the refresh to avoid slowing down typing
        self._update_timer.Start(300, oneShot=True)

    def _on_timer_refresh(self, event):
        """Actually perform the refresh after the debounce delay."""
        if not self.cost or not self.on_changed: return
        
        def safe_float(val_str, default=0.0):
            try:
                return float(val_str.replace(',', '.') or default)
            except ValueError:
                return default

        try:
            logger.debug(f"recalc_preview start | name={getattr(self.cost, 'name', '?')}")
            # We must be careful about which UI elements exist
            ptype = self.cost.pricing.pricing_type if self.cost.pricing else PricingType.PER_UNIT
            temp_pricing = PricingStructure(ptype)
            
            if self.cost.cost_type in [CostType.MATERIAL, CostType.SUBCONTRACTING]:
                temp_pricing.unit = self._ctrl_get_value('prop_unit', temp_pricing.unit, strip=True)
                temp_pricing.fixed_price = safe_float(str(self._ctrl_get_value('prop_fixed_price', temp_pricing.fixed_price)))
                temp_pricing.unit_price = safe_float(str(self._ctrl_get_value('prop_unit_price', temp_pricing.unit_price)))
                if self.cost.pricing:
                    temp_pricing.tiers = self.cost.pricing.tiers
            elif self.cost.cost_type == CostType.TOOLING:
                temp_pricing.fixed_price = safe_float(str(self._ctrl_get_value('prop_tool_price', 0.0)))
                temp_pricing.unit_price = 0.0
                temp_pricing.tiers = []
                temp_pricing.unit = "forfait"
            else:
                # Internal operation: ensure pricing is empty for preview
                temp_pricing.unit_price = 0
                temp_pricing.fixed_price = 0
                temp_pricing.tiers = []

            temp_cost = CostItem(self._ctrl_get_value('prop_name', "", strip=True), self.cost.cost_type, temp_pricing)
            temp_cost.comment = self._ctrl_get_value('prop_comment', "")
            temp_cost.is_active = bool(self._ctrl_get_value('prop_active', False))
            if self.cost.cost_type == CostType.TOOLING:
                temp_cost.client_comment = self._ctrl_get_value('prop_client_comment', "")
                temp_cost.margin_rate = 0.0
                temp_cost.conversion_factor = 1.0
                temp_cost.conversion_type = ConversionType.MULTIPLY
            else:
                temp_cost.conversion_factor = safe_float(str(self._ctrl_get_value('prop_conv_factor', 1.0)), 1.0)
                temp_cost.margin_rate = safe_float(str(self._ctrl_get_value('prop_margin_rate', 0.0)))
                cv_val = self._ctrl_get_selection('prop_conv_type', "Série (Multiplier)")
                temp_cost.conversion_type = ConversionType.MULTIPLY if "Série" in cv_val else ConversionType.DIVIDE
            
            # Include quantity per piece
            temp_cost.quantity_per_piece = safe_float(str(self._ctrl_get_value('prop_qty_per_piece', 1.0)), 1.0)
            if self.cost.cost_type in [CostType.MATERIAL, CostType.SUBCONTRACTING]:
                # Pièces gratuites issues de l'outillage de l'opération (pas de saisie sur l'offre)
                temp_cost._free_pieces = getattr(self.cost, "_free_pieces", None)
            temp_cost.quantity_per_piece_is_inverse = bool(self._ctrl_get_value('prop_qty_inverse', False))
            
            # Include supplier quote reference and documents for SUBCONTRACTING
            if self.cost.cost_type == CostType.SUBCONTRACTING:
                temp_cost.supplier_quote_ref = self._ctrl_get_value('prop_supplier_quote_ref', "", strip=True)
                if hasattr(self, 'doc_list'):
                    temp_cost.documents = self.doc_list.documents
            
            # Internal operation fields
            if self.cost.cost_type == CostType.INTERNAL_OPERATION:
                temp_cost.hourly_rate = safe_float(str(self._ctrl_get_value('prop_internal_rate', 0.0)))
                temp_cost.fixed_time = safe_float(str(self._ctrl_get_value('prop_fixed_h', 0.0)))
                temp_cost.per_piece_time = safe_float(str(self._ctrl_get_value('prop_piece_h', 0.0)))
                temp_cost.is_temps_masque = bool(self._ctrl_get_value('prop_temps_masque', False))
                self._refresh_serie_inherited(temp_cost)

            if self.cost.cost_type == CostType.TOOLING:
                self.on_changed(temp_cost)
                self._refresh_price_panel(self.cost)       # le parent vient d'appliquer les valeurs à la ligne
                return

            # Update dynamic consumption label context if needed
            if hasattr(self, 'prop_unit'):
                u = self._ctrl_get_value('prop_unit', "unité", strip=True) or "unité"
                inverse = bool(self._ctrl_get_value('prop_qty_inverse', False))
                label = f"Consommation (pièce/{u}):" if inverse else f"Consommation ({u}/pièce):"
                label_updated = self._ctrl_set_label('label_conso', label)
                if label_updated:
                    self.left_sizer.Layout()

            self._refresh_price_panel(temp_cost)           # aperçu en temps réel, avant application
            self.on_changed(temp_cost)
            logger.debug(f"recalc_preview done | name={getattr(self.cost, 'name', '?')}")
        except Exception: 
            logger.exception("recalc_preview failed")
            pass

    def _on_manage_tiers(self, event):
        from ui.dialogs.tiers_editor_dialog import TiersEditorDialog
        dlg = TiersEditorDialog(self, self.cost.pricing.tiers)
        if dlg.ShowModal() == wx.ID_OK:
            self.cost.pricing.tiers = dlg.get_tiers()
            self.notify_change()
        dlg.Destroy()
    
    def _on_temps_masque_changed(self, event):
        if not hasattr(self, 'prop_temps_masque'): return
        is_masked = self.prop_temps_masque.GetValue()
        if hasattr(self, 'prop_piece_h'): self.prop_piece_h.Enable(not is_masked)
        if hasattr(self, 'prop_piece_m'): self.prop_piece_m.Enable(not is_masked)
        if hasattr(self, 'prop_piece_s'): self.prop_piece_s.Enable(not is_masked)
        self.notify_change()
    
    
    def _refresh_price_panel(self, cost):
        """Prix de l'étape par quantité (temps, taux horaire final, CA, marge…), en temps réel."""
        op = self._owner_op()
        if cost is None or op is None or not self.project:
            self.price_panel.clear()
            return
        if cost is not self.cost:                          # valeurs saisies pas encore appliquées
            cost._free_pieces = getattr(self.cost, "_free_pieces", None)
        self.price_panel.load_cost(cost, op, self.project)
