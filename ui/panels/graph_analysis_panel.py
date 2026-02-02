# ui/panels/graph_analysis_panel.py
import wx
import math

class GraphAnalysisPanel(wx.Panel):
    """Visual analysis of price decomposition and evolution."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        # Removed potentially problematic BG_STYLE_PAINT
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Tools
        tool_sizer = wx.BoxSizer(wx.HORIZONTAL)
        tool_sizer.Add(wx.StaticText(self, label="Analyse pour la quantité :"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.qty_choice = wx.Choice(self)
        self.qty_choice.Bind(wx.EVT_CHOICE, lambda e: self.Refresh())
        tool_sizer.Add(self.qty_choice, 0, wx.ALL, 5)
        
        main_sizer.Add(tool_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Canvas
        self.canvas = wx.Panel(self)
        self.canvas.Bind(wx.EVT_PAINT, self._on_paint)
        self.canvas.Bind(wx.EVT_SIZE, lambda e: self.Refresh())
        main_sizer.Add(self.canvas, 1, wx.EXPAND)
        
        self.SetSizer(main_sizer)

    def load_project(self, project):
        self.project = project
        self._refresh_qtys()
        self.Refresh()

    def _refresh_qtys(self):
        curr = self.qty_choice.GetStringSelection()
        self.qty_choice.Clear()
        if self.project:
            for q in sorted(self.project.sale_quantities):
                self.qty_choice.Append(str(q))
        if curr and self.qty_choice.FindString(curr) != wx.NOT_FOUND:
            self.qty_choice.SetStringSelection(curr)
        elif self.qty_choice.GetCount() > 0:
            self.qty_choice.SetSelection(0)

    def refresh_data(self):
        self._refresh_qtys()
        self.Refresh()

    def _on_paint(self, event):
        dc = wx.PaintDC(self.canvas)
        gc = wx.GraphicsContext.Create(dc)
        if not gc or not self.project: return

        w, h = self.canvas.GetSize()
        if w < 100 or h < 100: return

        # Draw background
        gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        gc.DrawRectangle(0, 0, w, h)

        # Layout
        margin = 60
        h_macro = 80
        h_bar = (h - h_macro) * 0.55
        h_line = h - h_macro - h_bar
        
        self._draw_macro_indicators(gc, 0, 0, w, h_macro, margin)
        self._draw_bar_chart(gc, 0, h_macro, w, h_bar, margin)
        self._draw_line_chart(gc, 0, h_macro + h_bar, w, h_line, margin)

    def _draw_macro_indicators(self, gc, x, y, w, h, margin):
        qty_str = self.qty_choice.GetStringSelection()
        if not qty_str: return
        qty = int(qty_str)

        # Calculate macro data
        from domain.calculator import Calculator
        from domain.cost import CostType
        
        ca_total = self.project.total_price(qty) * qty
        
        total_h = 0
        prod_sales = 0
        purchase_cost = 0
        purchase_sales = 0
        
        for op in self.project.operations:
            for cost in op._get_active_costs():
                res = Calculator.calculate_item(cost, qty)
                cost_sales = res.unit_sale_price * qty
                
                if cost.cost_type == CostType.INTERNAL_OPERATION:
                    total_h += cost.fixed_time + (cost.per_piece_time * qty)
                    prod_sales += cost_sales
                else:
                    purchase_cost += res.batch_supplier_cost
                    purchase_sales += cost_sales
        
        eff_th = prod_sales / total_h if total_h > 0 else 0
        purchase_margin = ((purchase_sales - purchase_cost) / purchase_sales * 100) if purchase_sales > 0 else 0

        # Time Formatting
        if total_h >= 1.0:
            time_str = f"{total_h:.2f} h"
        else:
            time_str = f"{total_h * 60:.1f} min"

        # Draw Boxes
        box_count = 4
        box_w = (w - 2*margin) / box_count
        
        # Style
        gc.SetBrush(wx.Brush(wx.Colour(248, 249, 250)))
        gc.SetPen(wx.Pen(wx.Colour(220, 220, 220), 1))
        
        metrics = [
            ("CA TOTAL LOT", f"{ca_total:.2f} €"),
            ("TEMPS / ACHATS", f"{time_str} / {purchase_cost:.2f} €"),
            ("VENTE HEURE PROD.", f"{eff_th:.2f} €/h"),
            ("MARGE SUR ACHATS", f"{purchase_margin:.1f} %")
        ]

        for i, (label, value) in enumerate(metrics):
            bx = margin + i * box_w
            gc.DrawRoundedRectangle(bx + 5, y + 15, box_w - 10, h - 25, 4)
            
            gc.SetFont(wx.Font(7, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(100, 100, 100))
            gc.DrawText(label, bx + 15, y + 25)
            
            # Adjust font if string too long
            font_size = 13 if len(value) < 12 else 11
            gc.SetFont(wx.Font(font_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(0, 102, 204))
            gc.DrawText(value, bx + 15, y + 42)

    def _draw_bar_chart(self, gc, x, y, w, h, margin):
        qty_str = self.qty_choice.GetStringSelection()
        if not qty_str: return
        qty = int(qty_str)

        # Calculate data
        from domain.calculator import Calculator
        ops_data = []
        unit_p = self.project.total_price(qty)
        
        for op in self.project.operations:
            # Aggregate components from all costs in the operation
            total_unit_f = 0
            total_unit_v = 0
            for item in op._get_active_costs():
                res = Calculator.calculate_item(item, qty)
                total_unit_f += res.fixed_part
                total_unit_v += res.variable_part
            
            unit_op = total_unit_f + total_unit_v
            if unit_op > 0:
                percent = (unit_op / unit_p * 100) if unit_p > 0 else 0
                label = op.label if op.label else op.code
                ops_data.append((label, unit_op, percent, unit_op * qty, total_unit_f, total_unit_v))
        
        if not ops_data: 
            gc.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL), wx.Colour(150, 150, 150))
            gc.DrawText("Aucune donnée de coût à afficher", x + w/2 - 100, y + h/2)
            return

        max_val = max(d[1] for d in ops_data) * 1.2
        
        # Drawing params
        chart_w = w - 2 * margin
        chart_h = h - 1.5 * margin
        bar_w = (chart_w / len(ops_data)) * 0.6
        spacing = (chart_w / len(ops_data)) * 0.4
        
        # Grid lines (水平)
        gc.SetPen(wx.Pen(wx.Colour(240, 240, 240), 1))
        for i in range(5):
            gy = y + h - margin - (i+1) * (chart_h / 5)
            gc.StrokeLine(margin, gy, margin + chart_w, gy)
            val_grid = (max_val / 5) * (i+1)
            gc.SetFont(wx.Font(7, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(150, 150, 150))
            gc.DrawText(f"{val_grid:.2f}", margin - 35, gy - 7)

        # Legend
        lx = margin + chart_w - 150
        ly = y + 5
        # Variable box
        gc.SetBrush(wx.Brush(wx.Colour(100, 100, 100)))
        gc.DrawRectangle(lx, ly, 12, 12)
        gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.BLACK)
        gc.DrawText("Variable (Couleur unie)", lx + 18, ly - 2)
        # Amorti box
        gc.SetBrush(wx.Brush(wx.Colour(200, 200, 200, 180)))
        gc.DrawRectangle(lx, ly + 20, 12, 12)
        gc.DrawText("Amorti / Fixe (Couleur claire)", lx + 18, ly + 18)

        # Axes
        gc.SetPen(wx.Pen(wx.Colour(100, 100, 100), 1))
        gc.StrokeLine(margin, y + h - margin, margin + chart_w, y + h - margin) # X
        gc.StrokeLine(margin, y + margin, margin, y + h - margin) # Y
        
        # Title
        gc.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(50, 50, 50))
        gc.DrawText(f"Structure du Prix de Vente Unitaire (Lot de {qty} pces)", margin, y + 5)
        gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(100, 100, 100))
        gc.DrawText("Valeurs en €/pièce (Total lot entre parenthèses)", margin, y + 25)

        colors = [wx.Colour(70, 130, 180), wx.Colour(60, 179, 113), wx.Colour(245, 166, 35), wx.Colour(208, 2, 27), wx.Colour(144, 19, 254)]

        for i, (code, val, pct, total_lot, unit_f, unit_v) in enumerate(ops_data):
            bx = margin + i * (bar_w + spacing) + spacing/2
            
            # Heights
            bh_total = (val / max_val) * chart_h
            bh_f = (unit_f / max_val) * chart_h
            bh_v = (unit_v / max_val) * chart_h
            
            by_v = y + h - margin - bh_v
            by_f = by_v - bh_f
            by = by_f
            
            base_color = colors[i % len(colors)]
            
            # 1. Variable part (Bottom)
            gc.SetBrush(wx.Brush(base_color))
            gc.DrawRectangle(bx, by_v, bar_w, bh_v)
            
            # 2. Amorti part (Top)
            # Create a lighter version or crosshatched? Let's go with lighter.
            light_color = wx.Colour(
                min(255, base_color.Red() + 60),
                min(255, base_color.Green() + 60),
                min(255, base_color.Blue() + 60),
                180 # Alpha
            )
            gc.SetBrush(wx.Brush(light_color))
            gc.DrawRectangle(bx, by_f, bar_w, bh_f)
            
            # Label
            gc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(80, 80, 80))
            gc.DrawText(code, bx + bar_w/2 - 15, y + h - margin + 5)
            
            # Unit Value & Percentage
            gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.BLACK)
            gc.DrawText(f"{val:.2f}€", bx + bar_w/2 - 20, by - 32)
            gc.SetFont(wx.Font(7, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(100, 100, 100))
            gc.DrawText(f"({pct:.1f}%)", bx + bar_w/2 - 18, by - 21)
            gc.DrawText(f"{total_lot:.1f}€ lot", bx + bar_w/2 - 22, by - 11)

    def _draw_line_chart(self, gc, x, y, w, h, margin):
        qtys = sorted(self.project.sale_quantities)
        if len(qtys) < 1: 
            gc.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL), wx.Colour(150, 150, 150))
            gc.DrawText("Définissez des quantités dans l'onglet Projet pour voir l'évolution", x + w/2 - 200, y + h/2)
            return
        
        prices = [self.project.total_price(q) for q in qtys]
        max_p = max(prices) * 1.2 if prices else 1
        min_p = min(prices) * 0.8 if prices else 0
        if max_p == min_p: max_p += 1; min_p -= 1
        
        chart_w = w - 2 * margin
        chart_h = h - 1.5 * margin
        
        # Grid lines
        gc.SetPen(wx.Pen(wx.Colour(240, 240, 240), 1))
        for i in range(5):
            gy = y + h - margin - (i+1) * (chart_h / 5)
            gc.StrokeLine(margin, gy, margin + chart_w, gy)

        # Axes
        gc.SetPen(wx.Pen(wx.Colour(100, 100, 100), 1))
        gc.StrokeLine(margin, y + h - margin, margin + chart_w, y + h - margin)
        gc.StrokeLine(margin, y + margin, margin, y + h - margin)
        
        gc.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(50, 50, 50))
        gc.DrawText("Évolution du Prix Unitaire (€/pièce)", margin, y + 5)

        if len(qtys) > 1:
            points = []
            for i, p in enumerate(prices):
                px = margin + (i / (len(qtys)-1)) * chart_w
                py = y + h - margin - ((p - min_p) / (max_p - min_p)) * chart_h
                points.append((px, py))
            
            # Shadow line
            gc.SetPen(wx.Pen(wx.Colour(0, 0, 255, 50), 4))
            path_s = gc.CreatePath()
            path_s.MoveToPoint(points[0][0], points[0][1] + 2)
            for p in points[1:]: path_s.AddLineToPoint(p[0], p[1] + 2)
            gc.StrokePath(path_s)

            # Main Line
            gc.SetPen(wx.Pen(wx.Colour(0, 120, 215), 2))
            path = gc.CreatePath()
            path.MoveToPoint(*points[0])
            for p in points[1:]: path.AddLineToPoint(*p)
            gc.StrokePath(path)
            
            # Dots and Labels
            for i, (px, py) in enumerate(points):
                gc.SetBrush(wx.Brush(wx.Colour(0, 120, 215)))
                gc.DrawEllipse(px - 4, py - 4, 8, 8)
                gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.BLACK)
                gc.DrawText(f"Q{qtys[i]}", px - 10, y + h - margin + 8)
                gc.DrawText(f"{prices[i]:.2f}€", px - 15, py - 20)
        else:
            # Single point
            px = margin + chart_w / 2
            py = y + margin + chart_h / 2
            gc.SetBrush(wx.Brush(wx.Colour(0, 120, 215)))
            gc.DrawEllipse(px - 5, py - 5, 10, 10)
            gc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.BLACK)
            gc.DrawText(f"Q{qtys[0]}: {prices[0]:.2f}€", px + 15, py - 10)
