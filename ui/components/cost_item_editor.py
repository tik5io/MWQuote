# ui/components/cost_item_editor.py
import wx
import copy
import base64
import os
import tempfile
from domain.cost import CostItem, CostType, PricingType, PricingStructure, ConversionType, PricingTier
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
        
        self._build_ui()

    def _build_ui(self):
        # Main layout is HORIZONTAL
        self.main_h_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # LEFT COLUMN: Inputs (Scrolled for small screens)
        self.left_column = wx.ScrolledWindow(self, style=wx.VSCROLL)
        self.left_column.SetScrollRate(0, 20)
        self.left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 1. Base Properties (Name, Type)
        self.base_grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=8)
        self.base_grid.AddGrowableCol(1, 1)
        
        self.base_grid.Add(wx.StaticText(self.left_column, label="Désignation:"))
        self.prop_name = wx.TextCtrl(self.left_column)
        self.prop_name.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
        self.base_grid.Add(self.prop_name, 1, wx.EXPAND)
        
        self.prop_cost_type = wx.Choice(self.left_column, choices=[ct.value for ct in CostType])
        self.prop_cost_type.Bind(wx.EVT_CHOICE, self._on_cost_type_changed)
        self.base_grid.Add(self.prop_cost_type, 1, wx.EXPAND)
        
        # New: Active Checkbox (for Sous-traitance)
        self.base_grid.Add(wx.StaticText(self.left_column, label="État:"))
        self.prop_active = wx.CheckBox(self.left_column, label="Utiliser cette offre pour le chiffrage")
        self.prop_active.Bind(wx.EVT_CHECKBOX, lambda e: self.notify_change())
        self.base_grid.Add(self.prop_active, 1, wx.EXPAND)
        
        self.left_sizer.Add(self.base_grid, 0, wx.EXPAND | wx.ALL, 10)
        
        # 2. Dynamic fields container
        self.dynamic_sizer = wx.BoxSizer(wx.VERTICAL)
        self.left_sizer.Add(self.dynamic_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        self.left_column.SetSizer(self.left_sizer)
        self.main_h_sizer.Add(self.left_column, 1, wx.EXPAND)
        
        # SEPARATOR (Thin line)
        line = wx.StaticLine(self, style=wx.LI_VERTICAL)
        self.main_h_sizer.Add(line, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)
        
        # RIGHT COLUMN: Analysis & Info
        self.right_column = wx.Panel(self)
        self.right_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header for Analysis
        header = wx.StaticText(self.right_column, label="ANALYSE TEMPS RÉEL")
        header.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        header.SetForegroundColour(wx.Colour(100, 100, 100))
        self.right_sizer.Add(header, 0, wx.LEFT | wx.TOP, 10)

        # Quantity Analysis Container (Scrolled Cards)
        self.analysis_scroll = wx.ScrolledWindow(self.right_column, style=wx.VSCROLL)
        self.analysis_scroll.SetScrollRate(0, 10)
        self.analysis_sizer = wx.BoxSizer(wx.VERTICAL)
        self.analysis_scroll.SetSizer(self.analysis_sizer)
        self.right_sizer.Add(self.analysis_scroll, 1, wx.EXPAND | wx.ALL, 5)
        
        # SEPARATOR
        self.right_sizer.Add(wx.StaticLine(self.right_column), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Integrated Result Summary Panel (Bottom part of right column)
        from ui.components.result_summary_panel import ResultSummaryPanel
        self.result_panel = ResultSummaryPanel(self.right_column)
        self.right_sizer.Add(self.result_panel, 0, wx.EXPAND | wx.ALL, 5)
        
        self.right_column.SetSizer(self.right_sizer)
        self.main_h_sizer.Add(self.right_column, 1, wx.EXPAND)
        
        self.SetSizer(self.main_h_sizer)

    def load_cost(self, cost: CostItem, project):
        self._is_loading = True
        self._update_timer.Stop() # Prevent pending updates from previous cost
        try:
            logger.info(f"load_cost | name={getattr(cost, 'name', '?')} type={getattr(cost, 'cost_type', '?')}")
            self.cost = cost
            self.project = project
            self.prop_name.ChangeValue(cost.name or "")
            self.prop_cost_type.SetStringSelection(cost.cost_type.value)
            self.prop_active.SetValue(cost.is_active)
            
            # Show/hide active checkbox based on context (provided by parent via project if needed, 
            # or just always show if SUBCONTRACTING)
            from domain.operation import SUBCONTRACTING_TYPOLOGY
            # We assume the parent gives us a hint about the operation typology
            # For now, let's keep it simple: show if cost_type is SUBCONTRACTING
            self.prop_active.Show(cost.cost_type == CostType.SUBCONTRACTING)
            self.prop_active.GetContainingSizer().Layout()
            
            self._refresh_dynamic_fields()
            self._update_quantity_reminder()
            self.result_panel.load_item(cost, project)
            self.result_panel.Show()
            self.main_h_sizer.Layout()
        finally:
            self._is_loading = False

    def _on_cost_type_changed(self, event):
        if hasattr(self, "_is_loading") and self._is_loading: return
        new_val = self.prop_cost_type.GetStringSelection()
        for ct in CostType:
            if ct.value == new_val:
                self.cost.cost_type = ct
                break
        if self.cost.cost_type in [CostType.MATERIAL, CostType.SUBCONTRACTING] and not self.cost.pricing:
            self.cost.pricing = PricingStructure(PricingType.PER_UNIT)
        self._refresh_dynamic_fields()

    def _refresh_dynamic_fields(self):
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
                        self.doc_list = DocumentListPanel(self.left_column, label="Offres Fournisseur (PDF) :")
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
                op_sizer, op_grid = create_box_grid("DÉTAILS OPÉRATION")
                op_grid.Add(wx.StaticText(self.left_column, label="Taux horaire (€/h):"), 0, wx.ALIGN_CENTER_VERTICAL)
                self.prop_internal_rate = wx.TextCtrl(self.left_column, value=f"{cost.hourly_rate:.2f}")
                self.prop_internal_rate.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
                op_grid.Add(self.prop_internal_rate, 1, wx.EXPAND)
                self._add_detailed_time_row(op_grid, "Temps fixe:", cost.fixed_time, "fixed")
                self._add_detailed_time_row(op_grid, "Temps/pièce:", cost.per_piece_time, "piece")
                self.dynamic_sizer.Add(op_sizer, 0, wx.EXPAND | wx.BOTTOM, 10)

        # SECTION 3: PARAMÈTRES COMMERCIAUX & MÉTHODE (Common to all types)
        comm_sizer, comm_grid = create_box_grid("PARAMÈTRES COMMERCIAUX")
        
        comm_grid.Add(wx.StaticText(self.left_column, label="Type de conversion:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.prop_conv_type = wx.Choice(self.left_column, choices=[ct.value for ct in ConversionType])
        self.prop_conv_type.SetStringSelection(cost.conversion_type.value)
        self.prop_conv_type.Bind(wx.EVT_CHOICE, lambda e: self.notify_change())
        comm_grid.Add(self.prop_conv_type, 1, wx.EXPAND)

        comm_grid.Add(wx.StaticText(self.left_column, label="Facteur conversion:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.prop_conv_factor = wx.TextCtrl(self.left_column, value=f"{cost.conversion_factor:.4f}")
        self.prop_conv_factor.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
        comm_grid.Add(self.prop_conv_factor, 1, wx.EXPAND)

        comm_grid.Add(wx.StaticText(self.left_column, label="Marge (%):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.prop_margin_rate = wx.TextCtrl(self.left_column, value=f"{cost.margin_rate:.1f}")
        self.prop_margin_rate.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
        comm_grid.Add(self.prop_margin_rate, 1, wx.EXPAND)

        comm_grid.Add(wx.StaticText(self.left_column, label="Commentaire Méthode:"), 0, wx.TOP, 5)
        self.prop_comment = wx.TextCtrl(self.left_column, value=cost.comment or "", style=wx.TE_MULTILINE, size=(-1, 60))
        self.prop_comment.Bind(wx.EVT_TEXT, lambda e: self.notify_change())
        comm_grid.Add(self.prop_comment, 1, wx.EXPAND | wx.TOP, 5)

        self.dynamic_sizer.Add(comm_sizer, 0, wx.EXPAND)
        
        self.left_sizer.Layout()
        self.right_sizer.Layout()
        self.main_h_sizer.Layout()
        self.notify_change()

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
                
                # Clear pricing structure to avoid conflict in Calculator
                if self.cost.pricing:
                    self.cost.pricing.unit_price = 0
                    self.cost.pricing.fixed_price = 0
                    self.cost.pricing.tiers = []
            
            self.cost.conversion_factor = safe_float(self.prop_conv_factor.GetValue(), 1.0)
            self.cost.margin_rate = safe_float(self.prop_margin_rate.GetValue())
            self.cost.comment = self.prop_comment.GetValue()
            cv_val = self.prop_conv_type.GetStringSelection()
            self.cost.is_active = self.prop_active.GetValue()
            self.cost.conversion_type = ConversionType.MULTIPLY if cv_val == "Multiplier" else ConversionType.DIVIDE
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
                if hasattr(self, 'prop_unit'):
                    temp_pricing.unit = self.prop_unit.GetValue().strip()
                if hasattr(self, 'prop_fixed_price'):
                    temp_pricing.fixed_price = safe_float(self.prop_fixed_price.GetValue())
                if hasattr(self, 'prop_unit_price'):
                    temp_pricing.unit_price = safe_float(self.prop_unit_price.GetValue())
                if self.cost.pricing:
                    temp_pricing.tiers = self.cost.pricing.tiers
            else:
                # Internal operation: ensure pricing is empty for preview
                temp_pricing.unit_price = 0
                temp_pricing.fixed_price = 0
                temp_pricing.tiers = []

            temp_cost = CostItem(self.prop_name.GetValue().strip(), self.cost.cost_type, temp_pricing)
            temp_cost.conversion_factor = safe_float(self.prop_conv_factor.GetValue(), 1.0)
            temp_cost.margin_rate = safe_float(self.prop_margin_rate.GetValue())
            temp_cost.comment = self.prop_comment.GetValue()
            cv_val = self.prop_conv_type.GetStringSelection()
            temp_cost.is_active = self.prop_active.GetValue()
            temp_cost.conversion_type = ConversionType.MULTIPLY if cv_val == "Multiplier" else ConversionType.DIVIDE
            
            # Include quantity per piece
            if hasattr(self, 'prop_qty_per_piece'):
                temp_cost.quantity_per_piece = safe_float(self.prop_qty_per_piece.GetValue(), 1.0)
            if hasattr(self, 'prop_qty_inverse'):
                temp_cost.quantity_per_piece_is_inverse = self.prop_qty_inverse.GetValue()
            
            # Include supplier quote reference and documents for SUBCONTRACTING
            if self.cost.cost_type == CostType.SUBCONTRACTING:
                if hasattr(self, 'prop_supplier_quote_ref'):
                    temp_cost.supplier_quote_ref = self.prop_supplier_quote_ref.GetValue().strip()
                if hasattr(self, 'doc_list'):
                    temp_cost.documents = self.doc_list.documents
            
            # Internal operation fields
            if self.cost.cost_type == CostType.INTERNAL_OPERATION:
                if hasattr(self, 'prop_internal_rate'):
                    temp_cost.hourly_rate = safe_float(self.prop_internal_rate.GetValue())
                if hasattr(self, 'prop_fixed_h'):
                    temp_cost.fixed_time = safe_float(self.prop_fixed_h.GetValue())
                if hasattr(self, 'prop_piece_h'):
                    temp_cost.per_piece_time = safe_float(self.prop_piece_h.GetValue())

            # Update dynamic consumption label context if needed
            if hasattr(self, 'label_conso') and hasattr(self, 'prop_unit'):
                u = self.prop_unit.GetValue().strip() or "unité"
                inverse = self.prop_qty_inverse.GetValue() if hasattr(self, 'prop_qty_inverse') else False
                if inverse:
                    self.label_conso.SetLabel(f"Consommation (pièce/{u}):")
                else:
                    self.label_conso.SetLabel(f"Consommation ({u}/pièce):")
                self.left_sizer.Layout()

            self._update_quantity_reminder(temp_cost) # Pass temp_cost for preview
            self.result_panel.update_results(temp_cost)
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
    
    
    def _update_quantity_reminder(self, preview_cost=None):
        """Update the quantity reminder panel with detailed breakdown of needs and MOQ."""
        self.analysis_sizer.Clear(True)
        cost = preview_cost or self.cost
        if not cost or not self.project:
            self.analysis_scroll.Hide()
            return

        from domain.calculator import Calculator
        
        # 1. Section Header: MOQ Context
        moq = cost.get_moq()
        unit_label = cost.pricing.unit if cost.pricing else "u"
        
        if moq > 0:
            moq_info = wx.Panel(self.analysis_scroll)
            moq_info.SetBackgroundColour(wx.Colour(255, 245, 230)) # Light orange
            info_sizer = wx.BoxSizer(wx.VERTICAL)
            txt = wx.StaticText(moq_info, label=f"LOT MINIMUM (MOQ) : {moq} {unit_label}")
            txt.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            txt.SetForegroundColour(wx.Colour(150, 75, 0))
            info_sizer.Add(txt, 0, wx.ALL, 8)
            moq_info.SetSizer(info_sizer)
            self.analysis_sizer.Add(moq_info, 0, wx.EXPAND | wx.BOTTOM, 10)

        # 2. Results Cards
        for qty in sorted(self.project.sale_quantities):
            res = Calculator.calculate_item(cost, qty)
            
            card = wx.Panel(self.analysis_scroll)
            is_amortized = res.moq > 0 and res.quote_qty_needed < res.moq
            card.SetBackgroundColour(wx.Colour(255, 255, 255) if not is_amortized else wx.Colour(255, 240, 240))
            
            # Use a box sizer for the card
            card_sizer = wx.StaticBoxSizer(wx.VERTICAL, card, label=f"Pour {qty} pièces")
            
            grid = wx.FlexGridSizer(cols=2, hgap=15, vgap=2)
            grid.AddGrowableCol(1, 1)
            
            # Need
            grid.Add(wx.StaticText(card, label="Besoin Total:"), 0, wx.ALIGN_LEFT)
            need_txt = f"{res.quote_qty_needed:.2f} {unit_label}"
            if is_amortized:
                need_txt += f" (Amorti de {res.batch_supplier_cost:.2f}€)"
            st_need = wx.StaticText(card, label=need_txt)
            st_need.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            grid.Add(st_need, 1, wx.EXPAND)
            
            # Unit Cost (converted by factor)
            grid.Add(wx.StaticText(card, label="Coût Amorti:"), 0, wx.ALIGN_LEFT)
            st_cost = wx.StaticText(card, label=f"{res.unit_cost_converted:.2f} €/pc")
            st_cost.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            st_cost.SetForegroundColour(wx.Colour(0, 100, 0)) # Green
            grid.Add(st_cost, 1, wx.EXPAND)

            card_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 5)
            card.SetSizer(card_sizer)
            self.analysis_sizer.Add(card, 0, wx.EXPAND | wx.BOTTOM, 5)

        self.analysis_scroll.Show()
        self.right_sizer.Layout()
        self.right_column.Layout()
        self.main_h_sizer.Layout()
