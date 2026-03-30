import wx


class TypologyBarPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        self.data = []
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def set_data(self, rows):
        self.data = rows or []
        self.Refresh()

    def _on_paint(self, event):
        dc = wx.PaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        if not gc:
            return
        w, h = self.GetSize()
        gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        gc.DrawRectangle(0, 0, w, h)
        if not self.data:
            gc.DrawText("Aucune donnée", 10, 10)
            return

        top = self.data[:8]
        max_v = max([abs(float(r.get("avg_margin", 0.0))) for r in top] + [1.0])
        left = 12
        bar_area = w - 220
        bar_h = max(18, int((h - 20) / max(1, len(top))))
        y = 10
        for row in top:
            label = row.get("typology", "N/A")
            val = float(row.get("avg_margin", 0.0))
            bw = int((abs(val) / max_v) * bar_area)
            gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.BLACK)
            gc.DrawText(label[:26], left, y)
            gc.SetBrush(wx.Brush(wx.Colour(70, 130, 180)))
            gc.DrawRoundedRectangle(left + 130, y + 2, max(1, bw), bar_h - 6, 3)
            gc.DrawText(f"{val:.1f}%", left + 138 + bw, y)
            y += bar_h


class BusinessDashboardFrame(wx.Frame):
    def __init__(self, parent, analytics_service):
        super().__init__(parent, title="MWQuote - Business Dashboard", size=(980, 700))
        self.analytics_service = analytics_service
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        # KPI row
        kpi_row = wx.BoxSizer(wx.HORIZONTAL)
        self.kpi_total = wx.StaticText(panel, label="Projets: -")
        self.kpi_non_final = wx.StaticText(panel, label="Non finalisés: -")
        self.kpi_transform = wx.StaticText(panel, label="Tx transformation: -")
        self.kpi_exports = wx.StaticText(panel, label="Exports/projet: -")
        for k in [self.kpi_total, self.kpi_non_final, self.kpi_transform, self.kpi_exports]:
            k.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            kpi_row.Add(k, 1, wx.ALL | wx.EXPAND, 8)
        root.Add(kpi_row, 0, wx.EXPAND)

        split = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
        left = wx.Panel(split)
        right = wx.Panel(split)

        left_s = wx.BoxSizer(wx.VERTICAL)
        left_s.Add(wx.StaticText(left, label="Marge moyenne par client"), 0, wx.ALL, 6)
        self.client_list = wx.ListCtrl(left, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.client_list.InsertColumn(0, "Client", width=180)
        self.client_list.InsertColumn(1, "Marge Moy. (%)", width=120)
        self.client_list.InsertColumn(2, "Projets", width=80)
        left_s.Add(self.client_list, 1, wx.EXPAND | wx.ALL, 6)
        left.SetSizer(left_s)

        right_s = wx.BoxSizer(wx.VERTICAL)
        right_s.Add(wx.StaticText(right, label="Marge par typologie"), 0, wx.ALL, 6)
        self.typology_chart = TypologyBarPanel(right)
        right_s.Add(self.typology_chart, 1, wx.EXPAND | wx.ALL, 6)
        right.SetSizer(right_s)

        split.SplitVertically(left, right, 430)
        root.Add(split, 1, wx.EXPAND | wx.ALL, 5)

        refresh_btn = wx.Button(panel, label="Rafraîchir")
        refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self._load_data())
        root.Add(refresh_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(root)

    def _load_data(self):
        data = self.analytics_service.get_dashboard_data()
        k = data.get("kpis", {})
        self.kpi_total.SetLabel(f"Projets: {k.get('projects_total', 0)}")
        self.kpi_non_final.SetLabel(f"Non finalisés: {k.get('projects_non_finalized', 0)}")
        self.kpi_transform.SetLabel(f"Tx transformation: {k.get('transformation_rate_pct', 0.0):.1f}%")
        self.kpi_exports.SetLabel(f"Exports/projet: {k.get('avg_exports_per_project', 0.0):.2f}")

        self.client_list.DeleteAllItems()
        for row in data.get("margin_by_client", []):
            idx = self.client_list.InsertItem(self.client_list.GetItemCount(), str(row.get("client", "")))
            self.client_list.SetItem(idx, 1, f"{float(row.get('avg_margin', 0.0)):.2f}")
            self.client_list.SetItem(idx, 2, str(int(row.get("projects_count", 0))))

        self.typology_chart.set_data(data.get("margin_by_typology", []))
