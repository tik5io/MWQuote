# ui/components/result_summary_panel.py
import wx
from domain.cost import CostItem, CostType, ConversionType
from domain.operation import Operation

class ResultSummaryPanel(wx.Panel):
    """Component for showing real-time calculations (individual piece price, production time)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.item = None # CostItem or Operation
        self.project = None
        self.SetBackgroundColour(wx.Colour(245, 245, 255))
        self._build_ui()

    def _build_ui(self):
        # Apply a subtle border and rounded look if possible (via background and padding)
        self.SetBackgroundColour(wx.Colour(250, 252, 255))
        
        container_sizer = wx.BoxSizer(wx.VERTICAL)
        info_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header box
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.info_title = wx.StaticText(self, label="RÉSULTAT GLOBAL")
        self.info_title.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.info_title.SetForegroundColour(wx.Colour(50, 50, 100))
        header_sizer.Add(self.info_title, 0, wx.ALL, 10)
        info_sizer.Add(header_sizer, 0, wx.EXPAND)

        # Quantity Selector - Integrated row
        qty_panel = wx.Panel(self)
        # Simulation quantity selector (More integrated)
        qty_panel = wx.Panel(self)
        qty_panel.SetBackgroundColour(wx.Colour(230, 240, 255))
        qty_panel_sizer = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(qty_panel, label="Simulation pour Q =")
        lbl.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        qty_panel_sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        self.target_qty_choice = wx.Choice(qty_panel)
        self.target_qty_choice.Bind(wx.EVT_CHOICE, lambda e: self.update_results())
        qty_panel_sizer.Add(self.target_qty_choice, 0, wx.TOP | wx.BOTTOM | wx.LEFT, 5)
        qty_panel.SetSizer(qty_panel_sizer)
        info_sizer.Add(qty_panel, 0, wx.EXPAND | wx.BOTTOM, 10)

        # Main Price Display (Integrated Highlight)
        price_panel = wx.Panel(self)
        price_panel.SetBackgroundColour(wx.Colour(245, 248, 255))
        price_sizer = wx.BoxSizer(wx.VERTICAL)
        self.info_cost_piece = wx.StaticText(price_panel, label="Vente: - €/pc")
        self.info_cost_piece.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.info_cost_piece.SetForegroundColour(wx.Colour(0, 0, 180))
        price_sizer.Add(self.info_cost_piece, 0, wx.ALL, 10)
        price_panel.SetSizer(price_sizer)
        info_sizer.Add(price_panel, 0, wx.EXPAND | wx.BOTTOM, 10)

        # KPI GRID (Metrics & Indicators)
        metrics_grid = wx.FlexGridSizer(cols=3, hgap=10, vgap=10) # 3 columns to include MOQ if needed
        metrics_grid.AddGrowableCol(0, 1)
        metrics_grid.AddGrowableCol(1, 1)
        metrics_grid.AddGrowableCol(2, 1)

        # 1. PRODUCTION
        self.prod_box = wx.Panel(self)
        self.prod_box.SetBackgroundColour(wx.Colour(240, 240, 240))
        prod_sizer = wx.BoxSizer(wx.VERTICAL)
        lbl = wx.StaticText(self.prod_box, label="PRODUCTION")
        lbl.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        lbl.SetForegroundColour(wx.Colour(100, 100, 100))
        prod_sizer.Add(lbl, 0, wx.LEFT | wx.TOP, 8)
        self.info_prod_details = wx.StaticText(self.prod_box, label="-")
        self.info_prod_details.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        prod_sizer.Add(self.info_prod_details, 0, wx.ALL, 8)
        self.prod_box.SetSizer(prod_sizer)
        metrics_grid.Add(self.prod_box, 1, wx.EXPAND)

        # 2. ACHATS
        self.achat_box = wx.Panel(self)
        self.achat_box.SetBackgroundColour(wx.Colour(240, 240, 240))
        achat_sizer = wx.BoxSizer(wx.VERTICAL)
        lbl = wx.StaticText(self.achat_box, label="ACHATS")
        lbl.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        lbl.SetForegroundColour(wx.Colour(100, 100, 100))
        achat_sizer.Add(lbl, 0, wx.LEFT | wx.TOP, 8)
        self.info_achat_details = wx.StaticText(self.achat_box, label="-")
        self.info_achat_details.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        achat_sizer.Add(self.info_achat_details, 0, wx.ALL, 8)
        self.achat_box.SetSizer(achat_sizer)
        metrics_grid.Add(self.achat_box, 1, wx.EXPAND)

        # 3. MOQ Warning
        self.moq_box = wx.Panel(self)
        self.moq_box.SetBackgroundColour(wx.Colour(255, 240, 230))
        moq_sizer = wx.BoxSizer(wx.VERTICAL)
        lbl = wx.StaticText(self.moq_box, label="ALERTE MOQ")
        lbl.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        lbl.SetForegroundColour(wx.Colour(180, 90, 0))
        moq_sizer.Add(lbl, 0, wx.LEFT | wx.TOP, 8)
        self.moq_warning = wx.StaticText(self.moq_box, label="-")
        self.moq_warning.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.moq_warning.SetForegroundColour(wx.Colour(220, 120, 0))
        moq_sizer.Add(self.moq_warning, 0, wx.ALL, 8)
        self.moq_box.SetSizer(moq_sizer)
        metrics_grid.Add(self.moq_box, 1, wx.EXPAND)
        self.moq_box.Hide()

        info_sizer.Add(metrics_grid, 0, wx.EXPAND | wx.ALL, 5)
        
        # CA Summary
        self.info_ca_total = wx.StaticText(self, label="CA lot: - €")
        self.info_ca_total.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.info_ca_total.SetForegroundColour(wx.Colour(100, 100, 100))
        info_sizer.Add(self.info_ca_total, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        container_sizer.Add(info_sizer, 1, wx.EXPAND | wx.ALL, 2)
        self.SetSizer(container_sizer)

    def load_item(self, item, project):
        self.item = item
        self.project = project
        self._refresh_qty_choice()

    def _refresh_qty_choice(self):
        curr = self.target_qty_choice.GetStringSelection()
        self.target_qty_choice.Clear()
        if self.project:
            for q in sorted(self.project.sale_quantities):
                self.target_qty_choice.Append(str(q))
        if curr and self.target_qty_choice.FindString(curr) != wx.NOT_FOUND:
            self.target_qty_choice.SetStringSelection(curr)
        elif self.target_qty_choice.GetCount() > 0:
            self.target_qty_choice.SetSelection(0)
        self.update_results()

    def update_results(self, custom_item=None):
        """Force update with an optional custom item (for unsaved UI changes)."""
        item = custom_item or self.item
        if not item:
            self.Hide()
            return
        
        self.Show()
        try:
            from domain.calculator import Calculator
            qty_str = self.target_qty_choice.GetStringSelection()
            qty = int(qty_str) if qty_str else 1
            
            # Metrics aggregation
            total_h = 0
            prod_sales = 0
            purchase_cost = 0
            purchase_sales = 0
            
            # 1. Processing item(s)
            if isinstance(item, CostItem):
                res = Calculator.calculate_item(item, qty)
                val_pc = res.unit_sale_price
                val_total = res.unit_sale_price * qty
                title = f"Élément : {item.name}"
                
                # Update specific metrics
                if item.cost_type == CostType.INTERNAL_OPERATION:
                    total_h = item.fixed_time + (item.per_piece_time * qty)
                    prod_sales = val_total
                else: # Material or Subcontracting
                    purchase_cost = res.batch_supplier_cost
                    purchase_sales = val_total
            else: # Operation
                val_pc = item.total_with_margins(qty)
                val_total = val_pc * qty
                title = f"Opération : {item.label or item.code}"
                
                for cost in item.costs.values():
                    res = Calculator.calculate_item(cost, qty)
                    if cost.cost_type == CostType.INTERNAL_OPERATION:
                        total_h += cost.fixed_time + (cost.per_piece_time * qty)
                        prod_sales += res.unit_sale_price * qty
                    else:
                        purchase_cost += res.batch_supplier_cost
                        purchase_sales += res.unit_sale_price * qty

            # 2. Update KPI Boxes
            self.info_title.SetLabel(title.upper())
            self.info_cost_piece.SetLabel(f"Vente : {val_pc:.2f} €/pc")
            self.info_ca_total.SetLabel(f"CA lot simulation : {val_total:.2f} € (Q={qty})")
            
            # PRODUCTION Metric
            if total_h > 0:
                eff_rate = prod_sales / total_h
                time_str = f"{total_h:.2f}h" if total_h >= 1.0 else f"{total_h*60:.1f}min"
                self.info_prod_details.SetLabel(f"Temps: {time_str}\nVente Heure: {eff_rate:.2f} €/h")
                self.prod_box.Show()
            else:
                self.prod_box.Hide()

            # ACHATS Metric
            if purchase_cost > 0:
                p_margin = ((purchase_sales - purchase_cost) / purchase_sales * 100) if purchase_sales > 0 else 0
                self.info_achat_details.SetLabel(f"Total: {purchase_cost:.2f}€\nMarge: {p_margin:.1f}%")
                self.achat_box.Show()
            else:
                self.achat_box.Hide()

            # MOQ Alert check
            is_below_moq = False
            if isinstance(item, CostItem) and item.cost_type == CostType.SUBCONTRACTING:
                res = Calculator.calculate_item(item, qty)
                if res.quote_qty_needed < res.moq:
                    self.moq_warning.SetLabel(f"{res.moq} {item.pricing.unit}")
                    is_below_moq = True
            
            if is_below_moq: self.moq_box.Show()
            else: self.moq_box.Hide()
                
        except Exception:
            self.info_cost_piece.SetLabel("Prix vente/pc : ---")
            self.info_ca_total.SetLabel("CA généré : ---")
        
        self.Layout()
        if self.GetParent():
            self.GetParent().Layout()

    def _show_time_info(self, total_h):
        # Time Formatting
        if total_h >= 1.0:
            time_str = f"{total_h:.2f} h"
        elif total_h * 60 >= 1.0:
            time_str = f"{total_h * 60:.2f} min"
        else:
            time_str = f"{total_h * 3600:.2f} s"

        shifts = total_h / 8.0
        info = f"Total : {time_str}  |  Postes (8h) : {shifts:.2f}\nCalendaire (par équipe) :  1 éq: {shifts:.1f}j  •  2 éq: {shifts/2:.1f}j  •  3 éq: {shifts/3:.1f}j"
        self.info_time_details.SetLabel(info)
        self.time_box.Show()
