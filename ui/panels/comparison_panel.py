# ui/panels/comparison_panel.py
import wx
import os
import wx.grid
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
        
        # Splitter for Metrics/Table vs Charts
        self.main_splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        self.main_splitter.SetMinimumPaneSize(100)
        
        # --- Comparison Content (Scrolled) ---
        self.scroll = wx.ScrolledWindow(self.main_splitter)
        self.scroll.SetScrollRate(20, 20)
        self.grid_sizer = wx.FlexGridSizer(rows=0, cols=1, vgap=8, hgap=10)
        self.scroll.SetSizer(self.grid_sizer)
        
        # --- Smart Comparison Grid ---
        self.grid_container = wx.Panel(self.scroll)
        self.grid_sizer_v = wx.BoxSizer(wx.VERTICAL)
        
        lbl = wx.StaticText(self.grid_container, label="OFFRES DE VENTE (Smart Match / Quantités Projet 1)")
        lbl.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        lbl.SetForegroundColour(wx.Colour(100, 100, 100))
        self.grid_sizer_v.Add(lbl, 0, wx.ALL, 5)
        
        self.smart_grid = wx.grid.Grid(self.grid_container)
        self.smart_grid.CreateGrid(0, 0)
        self.smart_grid.EnableEditing(False)
        self.smart_grid.SetDefaultCellAlignment(wx.ALIGN_RIGHT, wx.ALIGN_CENTER_VERTICAL)
        self.grid_sizer_v.Add(self.smart_grid, 1, wx.EXPAND | wx.ALL, 5)
        
        self.grid_container.SetSizer(self.grid_sizer_v)
        self.grid_sizer.Add(self.grid_container, 0, wx.EXPAND | wx.ALL, 5)

        # --- Sub-Header for Metrics ---
        self.metric_lbl = wx.StaticText(self.scroll, label="DÉTAILS ANALYSE (Quantité sélectionnée)")
        self.metric_lbl.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.metric_lbl.SetForegroundColour(wx.Colour(100, 100, 100))
        self.grid_sizer.Add(self.metric_lbl, 0, wx.ALL | wx.TOP, 15)
        
        # Inner grid for metrics
        self.metrics_inner_grid = wx.FlexGridSizer(rows=0, cols=1, vgap=8, hgap=10)
        self.grid_sizer.Add(self.metrics_inner_grid, 0, wx.EXPAND | wx.ALL, 5)
        
        # --- Charts Section ---
        self.chart_panel = wx.Panel(self.main_splitter, size=(-1, 400))
        self.chart_panel.SetMinSize((-1, 200))
        self.chart_panel.Bind(wx.EVT_PAINT, self._on_paint_charts)
        
        # Split!
        self.main_splitter.SplitHorizontally(self.scroll, self.chart_panel, -300)
        self.main_splitter.SetSashGravity(1.0)
        
        main_sizer.Add(self.main_splitter, 1, wx.EXPAND | wx.ALL, 5)
        
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
        if not self.projects: return
        
        # 1. Update Smart Match Grid
        self.smart_grid.ClearGrid()
        if self.smart_grid.GetNumberRows() > 0: self.smart_grid.DeleteRows(0, self.smart_grid.GetNumberRows())
        if self.smart_grid.GetNumberCols() > 0: self.smart_grid.DeleteCols(0, self.smart_grid.GetNumberCols())
        
        base_qtys = sorted(self.projects[0].sale_quantities)
        self.smart_grid.AppendCols(len(self.projects))
        self.smart_grid.AppendRows(len(base_qtys))
        
        for i, p in enumerate(self.projects):
            self.smart_grid.SetColLabelValue(i, f"{p.name}\n({p.reference})")
        
        for i, q in enumerate(base_qtys):
            self.smart_grid.SetRowLabelValue(i, f"Qté: {q}")
            for j, p in enumerate(self.projects):
                price = p.total_price(q)
                self.smart_grid.SetCellValue(i, j, f"{price:.4f} €/pc")
                if j == 0:
                    self.smart_grid.SetCellBackgroundColour(i, j, wx.Colour(245, 245, 245))
        
        self.smart_grid.AutoSize()
        
        # 2. Update Metrics Inner Grid
        self.metrics_inner_grid.Clear(True)
        self.metrics_inner_grid.SetCols(len(self.projects) + 1)
        
        qty_str = self.qty_choice.GetStringSelection()
        qty = int(qty_str) if qty_str else 0
        
        labels = [
            "Projet / Réf",
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
            self.metrics_inner_grid.Add(t, 0, wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL)
            
            row_idx = labels.index(lbl)
            for p in self.projects:
                val = "-"
                # Note: Smart match also for metrics!
                unit_p = p.total_price(qty)
                if row_idx == 0: val = f"{p.name[:20]}...\n({p.reference})"
                elif row_idx == 1: val = f"{unit_p * qty:.2f} €"
                elif row_idx == 2 or row_idx == 3:
                    ps = 0; prod_s = 0
                    for op in p.operations:
                        for cost in op._get_active_costs():
                            res = Calculator.calculate_item(cost, qty)
                            if cost.cost_type == CostType.INTERNAL_OPERATION: prod_s += res.unit_sale_price * qty
                            else: ps += res.unit_sale_price * qty
                    total = ps + prod_s
                    if total > 0:
                        val = f"{ps/total*100:.1f} %" if row_idx == 2 else f"{prod_s/total*100:.1f} %"
                elif row_idx == 4:
                    pc = 0; ps = 0
                    for op in p.operations:
                        for cost in op._get_active_costs():
                            if cost.cost_type != CostType.INTERNAL_OPERATION:
                                res = Calculator.calculate_item(cost, qty)
                                pc += res.batch_supplier_cost
                                ps += res.unit_sale_price * qty
                    val = f"{((ps-pc)/ps*100):.1f} %" if ps > 0 else "0 %"
                elif row_idx == 5:
                    th = 0; ps = 0
                    for op in p.operations:
                        for cost in op._get_active_costs():
                            if cost.cost_type == CostType.INTERNAL_OPERATION:
                                res = Calculator.calculate_item(cost, qty)
                                th += cost.fixed_time + (cost.per_piece_time * qty)
                                ps += res.unit_sale_price * qty
                    val = f"{ps/th:.2f} €/h" if th > 0 else "0 €/h"
                elif row_idx == 6:
                    th = 0
                    for op in p.operations:
                        for cost in op._get_active_costs():
                            if cost.cost_type == CostType.INTERNAL_OPERATION:
                                th += cost.fixed_time + (cost.per_piece_time * qty)
                    val = f"{th:.2f} h"
                
                v = wx.StaticText(self.scroll, label=val)
                if row_idx == 0:
                    v.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
                    v.SetForegroundColour(wx.Colour(0, 102, 204))
                self.metrics_inner_grid.Add(v, 0, wx.ALIGN_RIGHT)

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
            # Smart match for charts too!
            up = p.total_price(qty)
            th = 0; ps = 0
            for op in p.operations:
                for cost in op._get_active_costs():
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
