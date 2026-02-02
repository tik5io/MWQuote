# ui/panels/graph_analysis_panel.py
import wx
import math

class GraphAnalysisPanel(wx.Panel):
    """Visual analysis of price decomposition and evolution."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self._build_ui()

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Tools - compact header
        tool_sizer = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(self, label="Quantité :")
        lbl.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        tool_sizer.Add(lbl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 3)
        self.qty_choice = wx.Choice(self)
        self.qty_choice.Bind(wx.EVT_CHOICE, lambda e: self.Refresh())
        tool_sizer.Add(self.qty_choice, 0, wx.ALL, 3)

        main_sizer.Add(tool_sizer, 0, wx.EXPAND | wx.LEFT | wx.TOP, 5)

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

    def refresh_quantities(self):
        """Rafraîchit les sélecteurs de quantités (alias pour cohérence API)."""
        self._refresh_qtys()

    def _on_paint(self, event):
        dc = wx.PaintDC(self.canvas)
        gc = wx.GraphicsContext.Create(dc)
        if not gc or not self.project:
            return

        w, h = self.canvas.GetSize()
        if w < 80 or h < 80:
            return

        # Draw background
        gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        gc.DrawRectangle(0, 0, w, h)

        # Adaptive layout based on available space
        is_compact = h < 350 or w < 400
        margin = 30 if is_compact else 50

        # Layout proportions
        h_macro = 55 if is_compact else 70
        remaining = h - h_macro
        h_bar = remaining * 0.55
        h_line = remaining * 0.45

        self._draw_macro_indicators(gc, 0, 0, w, h_macro, margin, is_compact)
        self._draw_bar_chart(gc, 0, h_macro, w, h_bar, margin, is_compact)
        self._draw_line_chart(gc, 0, h_macro + h_bar, w, h_line, margin, is_compact)

    def _draw_macro_indicators(self, gc, x, y, w, h, margin, is_compact=False):
        qty_str = self.qty_choice.GetStringSelection()
        if not qty_str:
            return
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
            time_str = f"{total_h:.1f}h"
        else:
            time_str = f"{total_h * 60:.0f}min"

        # Adaptive metrics based on space
        if is_compact:
            # Simplified 2-box layout for compact mode
            metrics = [
                ("CA LOT", f"{ca_total:.0f} €"),
                ("MARGE ACHATS", f"{purchase_margin:.0f}%")
            ]
            box_count = 2
        else:
            metrics = [
                ("CA TOTAL LOT", f"{ca_total:.0f} €"),
                ("TEMPS / ACHATS", f"{time_str} / {purchase_cost:.0f} €"),
                ("€/H PROD", f"{eff_th:.0f} €/h"),
                ("MARGE ACHATS", f"{purchase_margin:.0f}%")
            ]
            box_count = 4

        box_w = (w - 2 * margin) / box_count
        box_h = h - 10

        # Style
        gc.SetBrush(wx.Brush(wx.Colour(248, 249, 250)))
        gc.SetPen(wx.Pen(wx.Colour(220, 220, 220), 1))

        label_font_size = 6 if is_compact else 7
        value_font_size = 10 if is_compact else 12

        for i, (label, value) in enumerate(metrics):
            bx = margin + i * box_w
            gc.DrawRoundedRectangle(bx + 3, y + 5, box_w - 6, box_h, 3)

            # Label - centered
            gc.SetFont(wx.Font(label_font_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(100, 100, 100))
            lw, lh = gc.GetTextExtent(label)
            gc.DrawText(label, bx + (box_w - lw) / 2, y + 10)

            # Value - centered
            gc.SetFont(wx.Font(value_font_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(0, 102, 204))
            vw, vh = gc.GetTextExtent(value)
            gc.DrawText(value, bx + (box_w - vw) / 2, y + 10 + lh + 5)

    def _draw_bar_chart(self, gc, x, y, w, h, margin, is_compact=False):
        qty_str = self.qty_choice.GetStringSelection()
        if not qty_str:
            return
        qty = int(qty_str)

        # Calculate data
        from domain.calculator import Calculator
        ops_data = []
        unit_p = self.project.total_price(qty)

        for op in self.project.operations:
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
                # Truncate label for compact mode
                if is_compact and len(label) > 8:
                    label = label[:7] + "…"
                ops_data.append((label, unit_op, percent, unit_op * qty, total_unit_f, total_unit_v))

        if not ops_data:
            gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL), wx.Colour(150, 150, 150))
            text = "Aucune donnée"
            tw, th = gc.GetTextExtent(text)
            gc.DrawText(text, x + (w - tw) / 2, y + h / 2)
            return

        max_val = max(d[1] for d in ops_data) * 1.2
        if max_val == 0:
            max_val = 1

        # Drawing params - adaptive
        chart_w = w - 2 * margin
        chart_h = h - margin - 20
        bar_total_w = chart_w / len(ops_data)
        bar_w = bar_total_w * 0.65
        spacing = bar_total_w * 0.35

        # Title - compact
        title_font = 8 if is_compact else 10
        gc.SetFont(wx.Font(title_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(50, 50, 50))
        title = f"Prix unitaire Q={qty}" if is_compact else f"Structure du Prix Unitaire (Lot de {qty} pces)"
        gc.DrawText(title, margin, y + 2)

        # Skip grid lines in compact mode for cleaner look
        if not is_compact:
            gc.SetPen(wx.Pen(wx.Colour(240, 240, 240), 1))
            for i in range(3):
                gy = y + h - margin - (i + 1) * (chart_h / 3)
                gc.StrokeLine(margin, gy, margin + chart_w, gy)

        # Axes
        gc.SetPen(wx.Pen(wx.Colour(180, 180, 180), 1))
        gc.StrokeLine(margin, y + h - margin, margin + chart_w, y + h - margin)

        colors = [wx.Colour(70, 130, 180), wx.Colour(60, 179, 113), wx.Colour(245, 166, 35), wx.Colour(208, 2, 27), wx.Colour(144, 19, 254)]

        label_font = 7 if is_compact else 8
        value_font = 7 if is_compact else 8

        for i, (code, val, pct, total_lot, unit_f, unit_v) in enumerate(ops_data):
            bx = margin + i * bar_total_w + spacing / 2

            # Heights
            bh_v = (unit_v / max_val) * chart_h if max_val > 0 else 0
            bh_f = (unit_f / max_val) * chart_h if max_val > 0 else 0

            by_v = y + h - margin - bh_v
            by_f = by_v - bh_f

            base_color = colors[i % len(colors)]

            # Variable part (bottom)
            gc.SetBrush(wx.Brush(base_color))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawRectangle(bx, by_v, bar_w, bh_v)

            # Fixed part (top) - lighter
            light_color = wx.Colour(
                min(255, base_color.Red() + 60),
                min(255, base_color.Green() + 60),
                min(255, base_color.Blue() + 60)
            )
            gc.SetBrush(wx.Brush(light_color))
            gc.DrawRectangle(bx, by_f, bar_w, bh_f)

            # Label below bar - centered
            gc.SetFont(wx.Font(label_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(60, 60, 60))
            lw, lh = gc.GetTextExtent(code)
            gc.DrawText(code, bx + (bar_w - lw) / 2, y + h - margin + 2)

            # Value above bar - centered
            gc.SetFont(wx.Font(value_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.BLACK)
            val_text = f"{val:.1f}€" if is_compact else f"{val:.2f}€"
            vw, vh = gc.GetTextExtent(val_text)
            # Only show if there's space
            if by_f - 15 > y + 15:
                gc.DrawText(val_text, bx + (bar_w - vw) / 2, by_f - vh - 2)

                # Percentage below value (only in non-compact or if space)
                if not is_compact and by_f - 28 > y + 15:
                    gc.SetFont(wx.Font(6, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(100, 100, 100))
                    pct_text = f"({pct:.0f}%)"
                    pw, ph = gc.GetTextExtent(pct_text)
                    gc.DrawText(pct_text, bx + (bar_w - pw) / 2, by_f - vh - ph - 4)

    def _draw_line_chart(self, gc, x, y, w, h, margin, is_compact=False):
        qtys = sorted(self.project.sale_quantities)
        if len(qtys) < 1:
            gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL), wx.Colour(150, 150, 150))
            text = "Aucune quantité définie"
            tw, th = gc.GetTextExtent(text)
            gc.DrawText(text, x + (w - tw) / 2, y + h / 2)
            return

        prices = [self.project.total_price(q) for q in qtys]
        max_p = max(prices) * 1.15 if prices else 1
        min_p = min(prices) * 0.85 if prices else 0
        if max_p == min_p:
            max_p += 1
            min_p = max(0, min_p - 1)

        chart_w = w - 2 * margin
        chart_h = h - margin - 15

        # Title
        title_font = 8 if is_compact else 10
        gc.SetFont(wx.Font(title_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(50, 50, 50))
        title = "Évolution €/pc" if is_compact else "Évolution du Prix Unitaire (€/pièce)"
        gc.DrawText(title, margin, y + 2)

        # Skip detailed grid in compact mode
        if not is_compact:
            gc.SetPen(wx.Pen(wx.Colour(240, 240, 240), 1))
            for i in range(3):
                gy = y + h - margin - (i + 1) * (chart_h / 3)
                gc.StrokeLine(margin, gy, margin + chart_w, gy)

        # X Axis
        gc.SetPen(wx.Pen(wx.Colour(180, 180, 180), 1))
        gc.StrokeLine(margin, y + h - margin, margin + chart_w, y + h - margin)

        if len(qtys) > 1:
            points = []
            for i, p in enumerate(prices):
                px = margin + (i / (len(qtys) - 1)) * chart_w
                py = y + h - margin - ((p - min_p) / (max_p - min_p)) * chart_h
                points.append((px, py))

            # Main Line
            gc.SetPen(wx.Pen(wx.Colour(0, 120, 215), 2))
            path = gc.CreatePath()
            path.MoveToPoint(*points[0])
            for p in points[1:]:
                path.AddLineToPoint(*p)
            gc.StrokePath(path)

            # Dots and Labels
            dot_size = 5 if is_compact else 6
            label_font = 6 if is_compact else 7
            value_font = 7 if is_compact else 8

            for i, (px, py) in enumerate(points):
                gc.SetBrush(wx.Brush(wx.Colour(0, 120, 215)))
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.DrawEllipse(px - dot_size / 2, py - dot_size / 2, dot_size, dot_size)

                # Quantity label below axis - centered
                gc.SetFont(wx.Font(label_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(80, 80, 80))
                q_text = f"Q{qtys[i]}"
                qw, qh = gc.GetTextExtent(q_text)
                gc.DrawText(q_text, px - qw / 2, y + h - margin + 2)

                # Price above point - centered, only if space
                gc.SetFont(wx.Font(value_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.BLACK)
                p_text = f"{prices[i]:.1f}€" if is_compact else f"{prices[i]:.2f}€"
                pw, ph = gc.GetTextExtent(p_text)
                if py - ph - 5 > y + 15:
                    gc.DrawText(p_text, px - pw / 2, py - ph - 3)
        else:
            # Single point - centered
            px = margin + chart_w / 2
            py = y + margin + chart_h / 2
            gc.SetBrush(wx.Brush(wx.Colour(0, 120, 215)))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawEllipse(px - 4, py - 4, 8, 8)
            gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.BLACK)
            text = f"Q{qtys[0]}: {prices[0]:.2f}€"
            tw, th = gc.GetTextExtent(text)
            gc.DrawText(text, px - tw / 2, py + 10)
