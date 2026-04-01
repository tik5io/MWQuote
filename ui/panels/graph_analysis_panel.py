# ui/panels/graph_analysis_panel.py
import wx
import math
from datetime import datetime

class GraphAnalysisPanel(wx.Panel):
    """Visual analysis of price decomposition and evolution."""

    def __init__(self, parent):
        super().__init__(parent)
        self.project = None
        self.projects = []  # For comparison mode
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
        note_btn = wx.Button(self, label="Note de calcul projet...")
        note_btn.Bind(wx.EVT_BUTTON, self._on_show_project_calculation_note)
        tool_sizer.Add(note_btn, 0, wx.ALL, 3)

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

    def load_projects(self, projects):
        """Load multiple projects for comparison mode."""
        self.projects = projects
        self.project = projects[0] if projects else None  # Use first as reference
        self._refresh_qtys()
        self.Refresh()

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
        if self.projects:
            # In comparison mode, replace bar chart with stacked cost evolution
            self._draw_stacked_cost_evolution(gc, 0, h_macro, w, h_bar, margin, is_compact)
        else:
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
                    total_h += res.internal_time_hours
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

    def _draw_stacked_cost_evolution(self, gc, x, y, w, h, margin, is_compact=False):
        """Draw stacked cost evolution across quantities for multiple offers (projects).
        
        X-axis: Quantities
        Y-axis: Cumulative cost per piece (€/pc)
        Stacked operations with different colors per operation
        Overlaid projects with different line styles
        """
        qty_str = self.qty_choice.GetStringSelection()
        if not qty_str:
            gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL), wx.Colour(150, 150, 150))
            text = "Aucune quantité définie"
            tw, th = gc.GetTextExtent(text)
            gc.DrawText(text, x + (w - tw) / 2, y + h / 2)
            return

        if not self.projects:
            return

        # Get common quantities from all projects
        all_qtys = set()
        for proj in self.projects:
            all_qtys.update(proj.sale_quantities)
        qtys = sorted(list(all_qtys))

        if not qtys:
            return

        # Collect all unique operations across all projects
        all_ops_codes = {}
        for proj in self.projects:
            for op in proj.operations:
                if op.code not in all_ops_codes:
                    all_ops_codes[op.code] = op

        ops_list = list(all_ops_codes.values())
        if not ops_list:
            return

        from domain.calculator import Calculator
        from domain.cost import CostType

        # Build data: for each project, for each quantity, cumulative costs per operation
        projects_data = []
        max_cost = 0

        for proj in self.projects:
            qty_data = []
            for qty in qtys:
                # Stack costs per operation
                cumulative_costs = []
                cumsum = 0.0
                for op_code in [op.code for op in ops_list]:
                    op = None
                    for o in proj.operations:
                        if o.code == op_code:
                            op = o
                            break
                    
                    if op:
                        op_unit_cost = 0.0
                        for cost in op._get_active_costs():
                            res = Calculator.calculate_item(cost, qty)
                            op_unit_cost += res.unit_sale_price
                        cumsum += op_unit_cost
                        cumulative_costs.append(cumsum)
                    else:
                        cumulative_costs.append(cumsum)  # Same as previous

                qty_data.append(cumulative_costs)
                if cumsum > max_cost:
                    max_cost = cumsum

            projects_data.append((proj.name or proj.reference, qty_data))

        if max_cost == 0:
            max_cost = 1

        chart_w = w - 2 * margin
        chart_h = h - margin - 20

        # Title
        title_font = 8 if is_compact else 10
        gc.SetFont(wx.Font(title_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(50, 50, 50))
        title = "Évol. Coûts Empilés" if is_compact else "Évolution des Coûts par Opération (€/pièce)"
        gc.DrawText(title, margin, y + 2)

        # Grid
        if not is_compact:
            gc.SetPen(wx.Pen(wx.Colour(240, 240, 240), 1))
            for i in range(3):
                gy = y + h - margin - (i + 1) * (chart_h / 3)
                gc.StrokeLine(margin, gy, margin + chart_w, gy)

        # Axes
        gc.SetPen(wx.Pen(wx.Colour(180, 180, 180), 1))
        gc.StrokeLine(margin, y + h - margin, margin + chart_w, y + h - margin)
        gc.StrokeLine(margin, y + 15, margin, y + h - margin)

        # Operation colors - Colorblind-safe palette (Tol palette adapted)
        # Darker shades for better line contrast while maintaining accessibility
        op_colors = [
            wx.Colour(0, 102, 204),      # Dark Blue
            wx.Colour(204, 85, 0),        # Dark Orange (burnt orange)
            wx.Colour(0, 153, 102),       # Dark Teal/Green
            wx.Colour(153, 51, 102),      # Dark Magenta
            wx.Colour(153, 102, 0),       # Dark Brown/Gold
            wx.Colour(102, 102, 153),     # Dark Purple-Gray
            wx.Colour(102, 0, 102),       # Deep Purple
            wx.Colour(204, 0, 102),       # Dark Crimson
        ]

        # Project line styles (solid/dashed)
        project_styles = [
            ("solid", 2),
            ("dashed", 2),
            ("dotted", 2),
        ]

        # Draw each project's stacked lines
        for proj_idx, (proj_name, qty_data) in enumerate(projects_data):
            style_name, line_width = project_styles[proj_idx % len(project_styles)]
            
            # For each operation, draw a line that goes through all quantities
            for op_idx, op_code in enumerate([op.code for op in ops_list]):
                color = op_colors[op_idx % len(op_colors)]
                
                # Adjust transparency/brightness for overlay effect
                if proj_idx > 0:
                    # Slightly fade non-first projects
                    color = wx.Colour(
                        min(255, int(color.Red() * 0.85)),
                        min(255, int(color.Green() * 0.85)),
                        min(255, int(color.Blue() * 0.85))
                    )

                # Build path for this operation across all quantities
                path = gc.CreatePath()
                first_point = True

                for q_idx, qty in enumerate(qtys):
                    if q_idx < len(qty_data) and op_idx < len(qty_data[q_idx]):
                        cost_val = qty_data[q_idx][op_idx]
                        px = margin + (q_idx / (len(qtys) - 1) if len(qtys) > 1 else 0.5) * chart_w
                        py = y + h - margin - (cost_val / max_cost) * chart_h

                        if first_point:
                            path.MoveToPoint(px, py)
                            first_point = False
                        else:
                            path.AddLineToPoint(px, py)

                # Draw path
                if style_name == "solid":
                    gc.SetPen(wx.Pen(color, line_width))
                elif style_name == "dashed":
                    gc.SetPen(wx.Pen(color, line_width, wx.PENSTYLE_SHORT_DASH))
                else:  # dotted
                    gc.SetPen(wx.Pen(color, line_width, wx.PENSTYLE_DOT))

                gc.StrokePath(path)

        # Quantity labels
        label_font = 6 if is_compact else 7
        gc.SetFont(wx.Font(label_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(80, 80, 80))
        for q_idx, qty in enumerate(qtys):
            px = margin + (q_idx / (len(qtys) - 1) if len(qtys) > 1 else 0.5) * chart_w
            q_text = f"Q{qty}"
            qw, qh = gc.GetTextExtent(q_text)
            gc.DrawText(q_text, px - qw / 2, y + h - margin + 3)

        # Legend for operations
        if not is_compact:
            legend_x = margin + chart_w - 100
            legend_y = y + 15
            gc.SetFont(wx.Font(6, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(60, 60, 60))
            
            for op_idx, op_code in enumerate([op.code for op in ops_list]):
                if op_idx > 4:  # Limit legend to first 5 operations
                    break
                color = op_colors[op_idx % len(op_colors)]
                gc.SetBrush(wx.Brush(color))
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.DrawRectangle(legend_x, legend_y + op_idx * 15, 8, 8)
                gc.SetFont(wx.Font(6, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(60, 60, 60))
                gc.DrawText(f"Op {op_code[:3]}", legend_x + 12, legend_y + op_idx * 15)

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

    def _on_show_project_calculation_note(self, _event):
        if not self.project:
            wx.MessageBox("Aucun projet chargé.", "Information", wx.OK | wx.ICON_INFORMATION)
            return
        self._show_project_calculation_note()

    def _show_project_calculation_note(self):
        note_text = self._build_project_calculation_note()

        dlg = wx.Dialog(self, title="Note de calcul projet", size=(960, 720))
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

    def _build_project_calculation_note(self):
        from domain.calculator import Calculator
        from domain.cost import CostType

        def euros(value):
            return f"{value:.4f} EUR"

        def number(value):
            return f"{value:.4f}"

        quantities = []
        if self.project and getattr(self.project, "sale_quantities", None):
            quantities = sorted([q for q in self.project.sale_quantities if q and q > 0])
        if not quantities:
            quantities = [1]

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = []
        lines.append("NOTE DE CALCUL PROJET")
        lines.append("")
        lines.append(f"Date generation: {now_str}")
        lines.append(f"Projet: {self.project.display_name}")
        lines.append(f"Client: {self.project.client or '-'}")
        lines.append(f"Nombre operations: {len(self.project.operations)}")
        lines.append(f"Quantites analysees: {', '.join(str(q) for q in quantities)}")
        lines.append("")

        for qty in quantities:
            unit_sale_base = sum(op.total_with_margins(qty) for op in self.project.operations)
            volume_rate = self.project.volume_margin_rates.get(qty, 1.0)
            unit_sale_final = self.project.total_price(qty)
            lot_total = unit_sale_final * qty

            purchase_cost = 0.0
            purchase_sales = 0.0
            total_h = 0.0
            internal_sales = 0.0

            lines.append("=" * 90)
            lines.append(f"QUANTITE: {qty}")
            lines.append("-" * 90)
            lines.append(f"Prix unitaire base (somme operations): {euros(unit_sale_base)} / pc")
            lines.append(f"Taux marge volume applique: x {number(volume_rate)}")
            lines.append(f"Prix unitaire final projet: {euros(unit_sale_final)} / pc")
            lines.append(f"Chiffre d'affaires lot: {euros(lot_total)}")
            lines.append("")
            lines.append("DETAIL PAR OPERATION")

            for op in self.project.operations:
                op_unit_sale = 0.0
                op_batch_supplier = 0.0
                op_fixed_sale = 0.0
                op_variable_sale = 0.0

                active_costs = list(op._get_active_costs())
                lines.append(f"  Operation: {op.typology or '-'} | {op.label or op.code} ({len(active_costs)} cout(s))")

                if not active_costs:
                    lines.append("    - Aucun cout actif")
                    continue

                for cost in active_costs:
                    res = Calculator.calculate_item(cost, qty)
                    op_unit_sale += res.unit_sale_price
                    op_batch_supplier += res.batch_supplier_cost
                    op_fixed_sale += res.fixed_part
                    op_variable_sale += res.variable_part

                    if cost.cost_type == CostType.INTERNAL_OPERATION:
                        total_h += res.internal_time_hours
                        internal_sales += res.unit_sale_price * qty
                    else:
                        purchase_cost += res.batch_supplier_cost
                        purchase_sales += res.unit_sale_price * qty

                    lines.append(
                        "    - "
                        f"{cost.name}: unit_vte={euros(res.unit_sale_price)} | "
                        f"unit_revient={euros(res.unit_cost_converted)} | "
                        f"lot_achat={euros(res.batch_supplier_cost)} | "
                        f"qte_devis={number(res.quote_qty_ordered)} | "
                        f"marge={number(cost.margin_rate)}%"
                    )

                lines.append(
                    "    > Synthese operation: "
                    f"unit_vte={euros(op_unit_sale)} | "
                    f"unit_fixe_vte={euros(op_fixed_sale)} | "
                    f"unit_variable_vte={euros(op_variable_sale)} | "
                    f"lot_vte={euros(op_unit_sale * qty)} | "
                    f"lot_achat={euros(op_batch_supplier)}"
                )
                lines.append("")

            eff_prod_eur_per_h = (internal_sales / total_h) if total_h > 0 else 0.0
            purchase_margin_pct = ((purchase_sales - purchase_cost) / purchase_sales * 100.0) if purchase_sales > 0 else 0.0

            lines.append("INDICATEURS MACRO")
            lines.append(f"- Temps interne total: {number(total_h)} h")
            lines.append(f"- Productif interne (vente lot): {euros(internal_sales)}")
            lines.append(f"- Achats fournisseurs (cout lot): {euros(purchase_cost)}")
            lines.append(f"- Ventes sur achats (lot): {euros(purchase_sales)}")
            lines.append(f"- Efficacite productive: {euros(eff_prod_eur_per_h)} / h")
            lines.append(f"- Marge achats: {number(purchase_margin_pct)} %")
            lines.append("")

        lines.append("=" * 90)
        lines.append("NOTE")
        lines.append("- Cette note detaille les calculs projet pour verification et revue.")
        lines.append("- Les prix unitaires sont exprimes par piece (pc).")

        return "\n".join(lines)
