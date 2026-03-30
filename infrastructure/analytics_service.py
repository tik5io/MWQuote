from __future__ import annotations

import json
import statistics

from infrastructure.persistence import PersistenceService


class AnalyticsService:
    """Business analytics with lightweight incremental cache."""

    LARGE_DATASET_THRESHOLD = 10000

    def __init__(self, db):
        self.db = db

    def get_dashboard_data(self) -> dict:
        self.refresh_incremental_cache()
        return self._aggregate_from_cache()

    def refresh_incremental_cache(self):
        rows = self.db.search_projects(include_missing=False, sort_by="last_modified", sort_order="DESC")
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT project_id, last_modified FROM analytics_project_cache")
            existing = {r[0]: r[1] for r in cur.fetchall()}

            current_ids = set()
            for row in rows:
                pid = row["id"]
                current_ids.add(pid)
                lm = str(row.get("last_modified") or "")
                if existing.get(pid) == lm:
                    continue
                metrics = self._compute_project_metrics(row)
                cur.execute(
                    "INSERT OR REPLACE INTO analytics_project_cache "
                    "(project_id, last_modified, client, status, exports_count, avg_margin, typology_margins_json, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (
                        pid,
                        lm,
                        metrics["client"],
                        metrics["status"],
                        metrics["exports_count"],
                        metrics["avg_margin"],
                        json.dumps(metrics["typology_margins"], ensure_ascii=False),
                    ),
                )

            # remove deleted projects from cache
            for pid in existing.keys():
                if pid not in current_ids:
                    cur.execute("DELETE FROM analytics_project_cache WHERE project_id = ?", (pid,))

            cur.execute(
                "INSERT OR REPLACE INTO analytics_cache_meta (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                ("last_refresh_count", str(len(rows))),
            )
            conn.commit()

    def _compute_project_metrics(self, db_row) -> dict:
        filepath = db_row.get("filepath")
        project = PersistenceService.load_project(filepath)
        margins = []
        typology_map: dict[str, list[float]] = {}
        for op in project.operations:
            for cost in op._get_active_costs():
                m = float(getattr(cost, "margin_rate", 0.0) or 0.0)
                margins.append(m)
                typ = (op.typology or "N/A").strip() or "N/A"
                typology_map.setdefault(typ, []).append(m)

        typology_avg = {}
        for typ, values in typology_map.items():
            typology_avg[typ] = round(statistics.mean(values), 3) if values else 0.0

        devis_refs = db_row.get("devis_refs") or ""
        exports_count = len([x for x in devis_refs.split(",") if x.strip()])
        avg_margin = round(statistics.mean(margins), 3) if margins else 0.0
        return {
            "client": db_row.get("client") or "",
            "status": db_row.get("status") or "",
            "exports_count": exports_count,
            "avg_margin": avg_margin,
            "typology_margins": typology_avg,
        }

    def _aggregate_from_cache(self) -> dict:
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT client, status, exports_count, avg_margin, typology_margins_json FROM analytics_project_cache")
            rows = cur.fetchall()

        if not rows:
            return {
                "kpis": {
                    "projects_total": 0,
                    "projects_non_finalized": 0,
                    "transformation_rate_pct": 0.0,
                    "avg_exports_per_project": 0.0,
                },
                "margin_by_client": [],
                "margin_by_typology": [],
            }

        margins_by_client: dict[str, list[float]] = {}
        margins_by_typology: dict[str, list[float]] = {}
        finalized_count = 0
        transmitted_count = 0
        total_exports = 0

        for client, status, exports_count, avg_margin, typ_json in rows:
            margins_by_client.setdefault(client or "(vide)", []).append(float(avg_margin or 0.0))
            total_exports += int(exports_count or 0)
            if (status or "") == "Finalisée":
                finalized_count += 1
            if (status or "") == "Transmise":
                transmitted_count += 1

            try:
                tmap = json.loads(typ_json or "{}")
            except Exception:
                tmap = {}
            for typ, val in tmap.items():
                margins_by_typology.setdefault(typ, []).append(float(val or 0.0))

        total_projects = len(rows)
        non_finalized = len([1 for _, s, *_ in rows if (s or "") != "Finalisée"])
        transformation_rate = (transmitted_count / total_projects * 100.0) if total_projects else 0.0
        avg_exports = (total_exports / total_projects) if total_projects else 0.0

        by_client = [
            {"client": c, "avg_margin": round(statistics.mean(vals), 3), "projects_count": len(vals)}
            for c, vals in margins_by_client.items()
        ]
        by_client.sort(key=lambda x: x["avg_margin"], reverse=True)

        by_typology = [
            {"typology": t, "avg_margin": round(statistics.mean(vals), 3), "samples": len(vals)}
            for t, vals in margins_by_typology.items()
        ]
        by_typology.sort(key=lambda x: x["avg_margin"], reverse=True)

        return {
            "kpis": {
                "projects_total": total_projects,
                "projects_non_finalized": non_finalized,
                "transformation_rate_pct": round(transformation_rate, 2),
                "avg_exports_per_project": round(avg_exports, 2),
                "finalized_projects": finalized_count,
                "transmitted_projects": transmitted_count,
            },
            "margin_by_client": by_client[:20],
            "margin_by_typology": by_typology,
            "cache_mode": "incremental",
            "large_dataset": total_projects > self.LARGE_DATASET_THRESHOLD,
        }
