import wx


class BusinessDashboardFrame(wx.Frame):
    def __init__(self, parent, analytics_service):
        super().__init__(parent, title="MWProjet - Business Dashboard", size=(980, 700))
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

        left = wx.Panel(panel)

        left_s = wx.BoxSizer(wx.VERTICAL)
        left_s.Add(wx.StaticText(left, label="Marge moyenne par client"), 0, wx.ALL, 6)
        self.client_list = wx.ListCtrl(left, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.client_list.InsertColumn(0, "Client", width=180)
        self.client_list.InsertColumn(1, "Marge Moy. (%)", width=120)
        self.client_list.InsertColumn(2, "Projets", width=80)
        left_s.Add(self.client_list, 1, wx.EXPAND | wx.ALL, 6)
        left.SetSizer(left_s)

        root.Add(left, 1, wx.EXPAND | wx.ALL, 5)

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
