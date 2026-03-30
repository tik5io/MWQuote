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
        self.offer_checks = []
        self.chart_elements = []
        self.current_tooltip = None
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
        self.chart_panel.Bind(wx.EVT_LEFT_UP, self._on_chart_click)
        self.chart_panel.Bind(wx.EVT_MOTION, lambda e: self._on_chart_motion(e, self.chart_panel, None))
        self.chart_panel.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._on_chart_leave(self.chart_panel))

        # Toggle offres (visibilité)
        self.offer_checkbox_sizer = wx.BoxSizer(wx.HORIZONTAL)
        main_sizer.Add(self.offer_checkbox_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Split!
        self.main_splitter.SplitHorizontally(self.scroll, self.chart_panel, -300)
        self.main_splitter.SetSashGravity(1.0)
        
        main_sizer.Add(self.main_splitter, 1, wx.EXPAND | wx.ALL, 5)
        
        self.SetSizer(main_sizer)

    def load_projects(self, filepaths):
        self.projects = []
        # Limit to 2 projects for comparison
        max_projects = 2
        for fp in filepaths[:max_projects]:
            try:
                p = PersistenceService.load_project(fp)
                self.projects.append(p)
            except Exception:
                continue
        
        if not self.projects:
            return
        
        # Show warning if more than 2 projects selected
        if len(filepaths) > 2:
            wx.MessageBox(
                f"Only the first 2 projects will be compared.\nSelected: {len(filepaths)}, Using: {len(self.projects)}",
                "Comparison Limited",
                wx.OK | wx.ICON_INFORMATION
            )

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
        self._refresh_offer_checkboxes()
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

    def _refresh_offer_checkboxes(self):
        self.offer_checks = []
        self.offer_checkbox_sizer.Clear(True)

        for idx, proj in enumerate(self.projects):
            label = f"[x] Offre {idx + 1}: {proj.reference[:20]}"
            cb = wx.CheckBox(self, label=label)
            cb.SetValue(True)
            cb.Bind(wx.EVT_CHECKBOX, self._on_toggle_offer)
            self.offer_checkbox_sizer.Add(cb, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 10)
            self.offer_checks.append(cb)

        self.offer_checkbox_sizer.Layout()
        self.Layout()

    def _on_toggle_offer(self, event):
        self.Refresh()

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

        self.chart_elements = []

        # Draw stacked cost evolution instead of simple bars
        self._draw_stacked_cost_evolution_comparison(gc, w, h, dlg=None)

    def _draw_stacked_cost_evolution_comparison(self, gc, w, h, is_enlarged=False, dlg=None):
        """Draw stacked cost evolution across quantities for multiple offers.
        
        X-axis: Quantities
        Y-axis: Cumulative cost per piece (€/pc)
        Stacked operations with different colors
        Overlaid projects with different line styles
        """
        margin = 80 if is_enlarged else 40
        title_font = 14 if is_enlarged else 10
        axis_label_font = 8 if is_enlarged else 7
        axis_value_font = 8 if is_enlarged else 6
        legend_font = 7 if is_enlarged else 6
        qty_str = self.qty_choice.GetStringSelection()
        
        # Get common quantities from all projects
        all_qtys = set()
        for proj in self.projects:
            all_qtys.update(proj.sale_quantities)
        qtys = sorted(list(all_qtys))

        if not qtys:
            gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL), wx.Colour(150, 150, 150))
            text = "Aucune quantité commune"
            tw, th = gc.GetTextExtent(text)
            gc.DrawText(text, w / 2 - tw / 2, h / 2)
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
                        cumulative_costs.append(cumsum)

                qty_data.append(cumulative_costs)
                if cumsum > max_cost:
                    max_cost = cumsum

            projects_data.append((proj.name or proj.reference, proj.reference, qty_data))

        if max_cost == 0:
            max_cost = 1

        chart_w = w - 2 * margin
        chart_h = h - 60

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

        # Project visualization (1st: solid line, 2nd: colored area)
        # Only 2 projects max
        project_styles = [
            {"type": "line", "width": 2},  # First project: solid line
            {"type": "area", "width": 2},  # Second project: filled area
        ]

        # Title
        gc.SetFont(wx.Font(title_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(50, 50, 50))
        gc.DrawText("Évolution des Coûts par Opération (€/pièce)", margin, 5)

        # Grid
        gc.SetPen(wx.Pen(wx.Colour(240, 240, 240), 1))
        for i in range(3):
            gy = 30 + (i + 1) * (chart_h / 3)
            gc.StrokeLine(margin, gy, margin + chart_w, gy)

        # Axes
        gc.SetPen(wx.Pen(wx.Colour(180, 180, 180), 1))
        gc.StrokeLine(margin, 30 + chart_h, margin + chart_w, 30 + chart_h)
        gc.StrokeLine(margin, 30, margin, 30 + chart_h)

        # Y-axis scale labels
        gc.SetFont(wx.Font(axis_value_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(100, 100, 100))
        for i in range(4):
            val = max_cost * i / 3
            label = f"{val:.2f}€"
            gy = 30 + chart_h - (i / 3) * chart_h
            lw, lh = gc.GetTextExtent(label)
            gc.DrawText(label, margin - lw - 5, gy - lh / 2)

        # Draw each project's stacked visualization (1st as line, 2nd as colored area)
        # First pass: Draw filled areas (from highest to lowest operation for proper layering)
        for proj_idx, (proj_name, proj_ref, qty_data) in enumerate(projects_data):
            if proj_idx >= len(project_styles):
                break
            if self.offer_checks and proj_idx < len(self.offer_checks) and not self.offer_checks[proj_idx].GetValue():
                continue
            
            proj_style = project_styles[proj_idx]
            
            # Only draw filled areas for second project (colored areas)
            if proj_style["type"] != "area":
                continue
            
            # Draw operations in reverse order (highest first) so lower ops appear on top
            for op_idx in range(len(ops_list) - 1, -1, -1):
                op_code = ops_list[op_idx].code
                color = op_colors[op_idx % len(op_colors)]
                
                # Build path for this operation across all quantities
                points = []

                for q_idx, qty in enumerate(qtys):
                    if q_idx < len(qty_data) and op_idx < len(qty_data[q_idx]):
                        cost_val = qty_data[q_idx][op_idx]
                        px = margin + (q_idx / (len(qtys) - 1) if len(qtys) > 1 else 0.5) * chart_w
                        py = 30 + chart_h - (cost_val / max_cost) * chart_h
                        points.append((px, py))

                # Fill area
                if len(points) > 1:
                    # Close path to create filled area
                    area_path = gc.CreatePath()
                    area_path.MoveToPoint(points[0][0], points[0][1])
                    for px, py in points[1:]:
                        area_path.AddLineToPoint(px, py)
                    # Line back down to baseline
                    area_path.AddLineToPoint(points[-1][0], 30 + chart_h)
                    area_path.AddLineToPoint(points[0][0], 30 + chart_h)
                    area_path.CloseSubpath()
                    
                    light_color = wx.Colour(
                        min(255, int(color.Red() * 1.3)),
                        min(255, int(color.Green() * 1.3)),
                        min(255, int(color.Blue() * 1.3))
                    )
                    gc.SetBrush(wx.Brush(light_color))
                    gc.SetPen(wx.TRANSPARENT_PEN)
                    gc.FillPath(area_path)

        # Second pass: Draw all lines (from lowest to highest operation for proper visibility)
        for proj_idx, (proj_name, proj_ref, qty_data) in enumerate(projects_data):
            if proj_idx >= len(project_styles):
                break
            if self.offer_checks and proj_idx < len(self.offer_checks) and not self.offer_checks[proj_idx].GetValue():
                continue
            
            proj_style = project_styles[proj_idx]
            
            # Draw operations in reverse order (highest first = lowest index visually on top)
            for op_idx in range(len(ops_list) - 1, -1, -1):
                op_code = ops_list[op_idx].code
                color = op_colors[op_idx % len(op_colors)]
                
                # Build path for this operation across all quantities
                path = gc.CreatePath()
                first_point = True

                for q_idx, qty in enumerate(qtys):
                    if q_idx < len(qty_data) and op_idx < len(qty_data[q_idx]):
                        cost_val = qty_data[q_idx][op_idx]
                        px = margin + (q_idx / (len(qtys) - 1) if len(qtys) > 1 else 0.5) * chart_w
                        py = 30 + chart_h - (cost_val / max_cost) * chart_h

                        if first_point:
                            path.MoveToPoint(px, py)
                            first_point = False
                        else:
                            path.AddLineToPoint(px, py)
                        
                        # Store element data for tooltip
                        elem_data = {
                            'x': px,
                            'y': py,
                            'op_code': op_code,
                            'op_idx': op_idx,
                            'cost_val': cost_val,
                            'proj_name': proj_name,
                            'proj_ref': proj_ref,
                            'qty': qty,
                            'color': color
                        }
                        if dlg is not None:
                            dlg.chart_elements.append(elem_data)
                        else:
                            self.chart_elements.append(elem_data)

                # Draw line
                gc.SetPen(wx.Pen(color, int(proj_style["width"]), wx.PENSTYLE_SOLID))
                gc.StrokePath(path)
                
                # Draw outline for second project area
                if proj_style["type"] == "area":
                    gc.SetPen(wx.Pen(color, int(proj_style["width"]), wx.PENSTYLE_SOLID))
                    gc.StrokePath(path)

        # Quantity labels
        gc.SetFont(wx.Font(axis_label_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(80, 80, 80))
        for q_idx, qty in enumerate(qtys):
            px = margin + (q_idx / (len(qtys) - 1) if len(qtys) > 1 else 0.5) * chart_w
            q_text = f"Q{qty}"
            qw, qh = gc.GetTextExtent(q_text)
            gc.DrawText(q_text, px - qw / 2, 30 + chart_h + 5)

        # Legend - operation colors
        legend_x = margin + chart_w - (200 if is_enlarged else 160)
        legend_y = 35
        gc.SetFont(wx.Font(legend_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(60, 60, 60))
        
        op_legend_y = legend_y
        for op_idx, op_code in enumerate([op.code for op in ops_list]):
            if op_idx > 4:
                break
            color = op_colors[op_idx % len(op_colors)]
            gc.SetBrush(wx.Brush(color))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawRectangle(legend_x, op_legend_y + op_idx * 11, 8, 8)
            gc.DrawText(f"Op {op_code[:3]}", legend_x + 12, op_legend_y + op_idx * 11 - 2)
        
        # Legend - project line styles/areas (repositioned to avoid truncation)
        op_legend_y += (min(5, len(ops_list)) + 1) * 11
        
        # Reposition if needed to avoid truncation
        if op_legend_y + len(projects_data) * 14 + 30 > h - 40:
            legend_x = margin + 10
            op_legend_y = h - 50 - (len(projects_data) * 14)
        
        gc.SetFont(wx.Font(legend_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(50, 50, 50))
        gc.DrawText("Offers:", legend_x, op_legend_y)
        op_legend_y += 12
        
        for proj_idx, (proj_name, proj_ref, _) in enumerate(projects_data):
            if proj_idx >= len(project_styles):
                break
            style = project_styles[proj_idx]
            if style["type"] == "line":
                # Solid line
                gc.SetPen(wx.Pen(wx.Colour(0, 0, 0), int(style["width"]), wx.PENSTYLE_SOLID))
                gc.StrokeLine(legend_x, op_legend_y + proj_idx * 14, legend_x + 30, op_legend_y + proj_idx * 14)
            else:
                # Colored area
                gc.SetBrush(wx.Brush(wx.Colour(150, 150, 150)))
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.DrawRectangle(legend_x, op_legend_y + proj_idx * 14 - 6, 30, 10)
            
            gc.SetFont(wx.Font(legend_font, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(60, 60, 60))
            label = f"Offer {proj_idx + 1}: {proj_ref[:12]}" if len(proj_ref) > 12 else f"Offer {proj_idx + 1}: {proj_ref}"
            gc.DrawText(label, legend_x + 35, op_legend_y + proj_idx * 14 - 3)
        
        # Click hint (only in non-enlarged mode)
        if not is_enlarged:
            gc.SetFont(wx.Font(7, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL), wx.Colour(150, 150, 150))
            gc.DrawText("(Click to expand)", margin + 5, h - 35)

    def _on_chart_click(self, event):
        """Handle click on chart to open enlarged view."""
        if self.projects:
            self._show_enlarged_chart()

    def _on_chart_motion(self, event, panel, dlg=None):
        """Handle mouse motion to show tooltips on chart elements."""
        elements = dlg.chart_elements if (dlg is not None and hasattr(dlg, 'chart_elements')) else self.chart_elements
        if not elements:
            return

        x, y = event.GetPosition()
        hover_distance = 15  # pixels

        # Find closest element
        closest_elem = None
        closest_dist = hover_distance
        for elem in elements:
            dist = ((elem['x'] - x) ** 2 + (elem['y'] - y) ** 2) ** 0.5
            if dist < closest_dist:
                closest_dist = dist
                closest_elem = elem

        current = dlg.current_tooltip if dlg is not None and hasattr(dlg, 'current_tooltip') else self.current_tooltip
        if closest_elem:
            if current != closest_elem:
                if dlg is not None and hasattr(dlg, 'current_tooltip'):
                    dlg.current_tooltip = closest_elem
                else:
                    self.current_tooltip = closest_elem
                self._show_tooltip(panel, dlg, closest_elem, x, y)
        else:
            if current is not None:
                if dlg is not None and hasattr(dlg, 'current_tooltip'):
                    dlg.current_tooltip = None
                else:
                    self.current_tooltip = None
                panel.SetToolTip(None)

    def _on_chart_leave(self, panel_or_dlg):
        """Hide tooltip when mouse leaves chart area."""
        if isinstance(panel_or_dlg, wx.Window):
            panel_or_dlg.SetToolTip(None)
            self.current_tooltip = None
        elif hasattr(panel_or_dlg, 'current_tooltip'):
            panel_or_dlg.current_tooltip = None


    def _show_tooltip(self, panel, dlg, elem, x, y):
        """Display tooltip for chart element."""
        op_code = elem['op_code']
        cost_val = elem['cost_val']
        proj_name = elem['proj_name']
        qty = elem['qty']
        
        # Format tooltip text
        tooltip_text = (
            f"Operation: {op_code}\n"
            f"Cost: {cost_val:.2f} €/pc\n"
            f"Quantity: {qty}\n"
            f"Offer: {proj_name}"
        )
        
        panel.SetToolTip(wx.ToolTip(tooltip_text))

    def _show_enlarged_chart(self):
        """Open a full-screen or large window with the stacked cost evolution chart."""
        dlg = wx.Dialog(self, title="Stacked Cost Evolution - Full View", size=(1200, 800),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        
        # Store chart elements for tooltip handling
        dlg.chart_elements = []
        dlg.current_tooltip = None
        
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Chart panel
        chart_panel = wx.Panel(dlg)
        chart_panel.Bind(wx.EVT_PAINT, lambda e: self._on_enlarged_paint(e, chart_panel, dlg))
        chart_panel.Bind(wx.EVT_MOTION, lambda e: self._on_chart_motion(e, chart_panel, dlg))
        chart_panel.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._on_chart_leave(dlg))
        
        main_sizer.Add(chart_panel, 1, wx.EXPAND)
        
        # Close button
        close_btn = wx.Button(dlg, wx.ID_CLOSE, "Close")
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        main_sizer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        dlg.SetSizer(main_sizer)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_enlarged_paint(self, event, panel, dlg):
        """Paint enlarged chart on the panel."""
        dc = wx.PaintDC(panel)
        gc = wx.GraphicsContext.Create(dc)
        if not gc or not self.projects:
            return
        
        w, h = panel.GetSize()
        dlg.chart_elements = []  # Clear previous elements
        self._draw_stacked_cost_evolution_comparison(gc, w, h, is_enlarged=True, dlg=dlg)
