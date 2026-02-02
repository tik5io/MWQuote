# ui/panels/comparison_panel.py
import wx
import os
from infrastructure.persistence import PersistenceService
from domain.calculator import Calculator
from domain.cost import CostType

class ComparisonPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        
        self.projects = []
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # --- Top bar with common quantity selection ---
        tool_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.header_lbl = wx.StaticText(self, label="COMPARAISON MULTIPLE")
        self.header_lbl.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        tool_sizer.Add(self.header_lbl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)
        
        tool_sizer.AddStretchSpacer(1)
        
        tool_sizer.Add(wx.StaticText(self, label="Quantité :"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)
        self.qty_choice = wx.Choice(self)
        self.qty_choice.Bind(wx.EVT_CHOICE, self._on_qty_change)
        tool_sizer.Add(self.qty_choice, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)
        
        main_sizer.Add(tool_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)
        
        # --- Comparison Grid (Scrolled) ---
        self.scroll = wx.ScrolledWindow(self)
        self.scroll.SetScrollRate(20, 20)
        # Fix: rows=0 to allow any number of rows
        self.grid_sizer = wx.FlexGridSizer(rows=0, cols=1, vgap=8, hgap=10)
        
        self.scroll.SetSizer(self.grid_sizer)
        main_sizer.Add(self.scroll, 1, wx.EXPAND | wx.ALL, 5)
        
        # --- Charts Section ---
        self.chart_panel = wx.Panel(self, size=(-1, 260))
        self.chart_panel.Bind(wx.EVT_PAINT, self._on_paint_charts)
        main_sizer.Add(self.chart_panel, 0, wx.EXPAND | wx.ALL, 5)
        
        self.SetSizer(main_sizer)

    def load_projects(self, filepaths):
        self.projects = []
        for fp in filepaths:
            try:
                p = PersistenceService.load_project(fp)
                self.projects.append(p)
            except Exception:
                continue
        
        if not self.projects:
            return

        # Refresh quantities
        all_qtys = set()
        for p in self.projects:
            all_qtys.update(p.sale_quantities)
        
        curr = self.qty_choice.GetStringSelection()
        self.qty_choice.Clear()
        for q in sorted(list(all_qtys)):
            self.qty_choice.Append(str(q))
            
        if curr and self.qty_choice.FindString(curr) != wx.NOT_FOUND:
            self.qty_choice.SetStringSelection(curr)
        else:
            # Try to select common qty
            common = set(self.projects[0].sale_quantities)
            for p in self.projects[1:]:
                common &= set(p.sale_quantities)
            if common:
                self.qty_choice.SetStringSelection(str(sorted(list(common))[0]))
            elif self.qty_choice.GetCount() > 0:
                self.qty_choice.SetSelection(0)
                
        self._update_comparison_grid()
        self.Refresh()

    def _on_qty_change(self, event):
        self._update_comparison_grid()
        self.Refresh()

    def _update_comparison_grid(self):
        self.grid_sizer.Clear(True)
        # Set column count based on projects
        self.grid_sizer.SetCols(len(self.projects) + 1)
        
        qty_str = self.qty_choice.GetStringSelection()
        qty = int(qty_str) if qty_str else 0
        
        labels = [
            "Projet / Réf",
            "Vente Unit. (€/pc)",
            "Vente Totale (Lot)",
            "Répart. Achats (%)",
            "Répart. Interne (%)",
            "Marge / Achats (%)",
            "Vente Heure (€/h)",
            "Temps Total (h)"
        ]
        
        for lbl in labels:
            t = wx.StaticText(self.scroll, label=lbl)
            t.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            self.grid_sizer.Add(t, 0, wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL)
            
            row_idx = labels.index(lbl)
            for p in self.projects:
                val = "-"
                if qty in p.sale_quantities:
                    unit_p = p.total_price(qty)
                    if row_idx == 0: val = f"{p.name[:20]}...\n({p.reference})"
                    elif row_idx == 1: val = f"{unit_p:.2f} €/pc"
                    elif row_idx == 2: val = f"{unit_p * qty:.2f} €"
                    elif row_idx == 3 or row_idx == 4:
                        ps = 0; prod_s = 0
                        for op in p.operations:
                            for cost in op.costs.values():
                                res = Calculator.calculate_item(cost, qty)
                                if cost.cost_type == CostType.INTERNAL_OPERATION: prod_s += res.unit_sale_price * qty
                                else: ps += res.unit_sale_price * qty
                        total = ps + prod_s
                        if total > 0:
                            val = f"{ps/total*100:.1f} %" if row_idx == 3 else f"{prod_s/total*100:.1f} %"
                    elif row_idx == 5:
                        pc = 0; ps = 0
                        for op in p.operations:
                            for cost in op.costs.values():
                                if cost.cost_type != CostType.INTERNAL_OPERATION:
                                    res = Calculator.calculate_item(cost, qty)
                                    pc += res.batch_supplier_cost
                                    ps += res.unit_sale_price * qty
                        val = f"{((ps-pc)/ps*100):.1f} %" if ps > 0 else "0 %"
                    elif row_idx == 6:
                        th = 0; ps = 0
                        for op in p.operations:
                            for cost in op.costs.values():
                                if cost.cost_type == CostType.INTERNAL_OPERATION:
                                    res = Calculator.calculate_item(cost, qty)
                                    th += cost.fixed_time + (cost.per_piece_time * qty)
                                    ps += res.unit_sale_price * qty
                        val = f"{ps/th:.2f} €/h" if th > 0 else "0 €/h"
                    elif row_idx == 7:
                        th = 0
                        for op in p.operations:
                            for cost in op.costs.values():
                                if cost.cost_type == CostType.INTERNAL_OPERATION:
                                    th += cost.fixed_time + (cost.per_piece_time * qty)
                        val = f"{th:.2f} h"
                
                v = wx.StaticText(self.scroll, label=val)
                if row_idx == 0:
                    v.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
                    v.SetForegroundColour(wx.Colour(0, 102, 204))
                self.grid_sizer.Add(v, 0, wx.ALIGN_RIGHT)

        self.grid_sizer.Layout()
        self.scroll.Layout()
        self.Layout()

    def _on_paint_charts(self, event):
        dc = wx.PaintDC(self.chart_panel)
        gc = wx.GraphicsContext.Create(dc)
        if not gc: return

        w, h = self.chart_panel.GetSize()
        qty_str = self.qty_choice.GetStringSelection()
        qty = int(qty_str) if qty_str else 0

        gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        gc.DrawRectangle(0, 0, w, h)
        if not self.projects: return

        margin = 40
        chart_w = w - 2*margin
        chart_h = h - 60
        
        data = []
        max_p = 0; max_e = 0
        for p in self.projects:
            if qty in p.sale_quantities:
                up = p.total_price(qty)
                th = 0; ps = 0
                for op in p.operations:
                    for cost in op.costs.values():
                        if cost.cost_type == CostType.INTERNAL_OPERATION:
                            res = Calculator.calculate_item(cost, qty)
                            th += cost.fixed_time + (cost.per_piece_time * qty)
                            ps += res.unit_sale_price * qty
                eff = ps / th if th > 0 else 0
                data.append((p.reference, up, eff))
                max_p = max(max_p, up); max_e = max(max_e, eff)

        if not data: return
        
        bw = (chart_w / len(data)) * 0.35
        col1 = wx.Colour(0, 102, 204); col2 = wx.Colour(255, 128, 0)
        
        for i, (ref, up, eff) in enumerate(data):
            gx = margin + i * (chart_w / len(data))
            hp = (up/max_p*chart_h) if max_p > 0 else 0
            he = (eff/max_e*chart_h) if max_e > 0 else 0
            
            gc.SetBrush(wx.Brush(col1))
            gc.DrawRectangle(gx + 5, h - 30 - hp, bw, hp)
            gc.SetBrush(wx.Brush(col2))
            gc.DrawRectangle(gx + bw + 10, h - 30 - he, bw, he)
            
            gc.SetFont(wx.Font(7, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.BLACK)
            gc.DrawText(ref, gx + 5, h - 25)

        gc.SetBrush(wx.Brush(col1))
        gc.DrawRectangle(margin, 5, 12, 12)
        gc.DrawText("Prix Unit.", margin + 15, 5)
        gc.SetBrush(wx.Brush(col2))
        gc.DrawRectangle(margin + 100, 5, 12, 12)
        gc.DrawText("Ef. (€/h)", margin + 115, 5)
