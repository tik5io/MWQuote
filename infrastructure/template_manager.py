from __future__ import annotations

import json
import statistics
from datetime import datetime

import domain.cost as domain_cost
from domain.operation import Operation


class TemplateManager:
    """Manage operation templates and usage tracking."""

    def __init__(self, db):
        self.db = db

    def list_templates(self, typology: str | None = None):
        with self.db.get_connection() as conn:
            conn.row_factory = None
            cur = conn.cursor()
            if typology:
                cur.execute(
                    "SELECT id, name, typology, config_json, tags, updated_at FROM operation_templates "
                    "WHERE typology = ? ORDER BY updated_at DESC, id DESC",
                    (typology,),
                )
            else:
                cur.execute(
                    "SELECT id, name, typology, config_json, tags, updated_at FROM operation_templates "
                    "ORDER BY typology, updated_at DESC, id DESC"
                )
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0],
                "name": r[1],
                "typology": r[2],
                "config": json.loads(r[3]) if r[3] else {},
                "tags": [t for t in (r[4] or "").split(",") if t],
                "updated_at": r[5],
            })
        return out

    def save_template_from_operation(self, operation: Operation, template_name: str, tags: list[str] | None = None):
        payload = self._operation_to_template_payload(operation)
        tags_csv = ",".join(tags or [])
        now = datetime.now().isoformat(timespec="seconds")
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO operation_templates (name, typology, config_json, tags, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (template_name, operation.typology or "", json.dumps(payload, ensure_ascii=False), tags_csv, now, now),
            )
            conn.commit()
            return cur.lastrowid

    def build_operation_from_template(self, template: dict) -> Operation:
        cfg = template.get("config", {}) or {}
        op = Operation(
            code=(template.get("typology") or "TPL"),
            label=template.get("name") or "Nouvelle",
            typology=template.get("typology") or "",
            comment=cfg.get("operation_comment", ""),
            template_id=template.get("id"),
            template_name=template.get("name", ""),
            template_snapshot=cfg,
            template_drift_score=0.0,
        )
        costs = cfg.get("costs", [])
        for c in costs:
            ct = self._cost_type_from_value(c.get("cost_type"))
            pricing_type = self._pricing_type_from_value(c.get("pricing_type"))
            pricing = domain_cost.PricingStructure(
                pricing_type=pricing_type,
                fixed_price=float(c.get("fixed_price", 0.0) or 0.0),
                unit_price=float(c.get("unit_price", 0.0) or 0.0),
                unit=c.get("unit", "pièce"),
                tiers=[],
            )
            cost = domain_cost.CostItem(
                name=c.get("name") or "Coût",
                cost_type=ct,
                pricing=pricing,
                fixed_time=float(c.get("fixed_time", 0.0) or 0.0),
                per_piece_time=float(c.get("per_piece_time", 0.0) or 0.0),
                hourly_rate=float(c.get("hourly_rate", 0.0) or 0.0),
                margin_rate=float(c.get("margin_rate", 0.0) or 0.0),
                quantity_per_piece=float(c.get("quantity_per_piece", 1.0) or 1.0),
                quantity_per_piece_is_inverse=bool(c.get("quantity_per_piece_is_inverse", False)),
                comment=c.get("comment", ""),
            )
            op.costs[cost.name] = cost
        return op

    def compute_drift_score(self, operation: Operation) -> float:
        snapshot = operation.template_snapshot or {}
        if not snapshot:
            return 0.0

        baseline_costs = snapshot.get("costs", [])
        current_costs = list(operation.costs.values())
        if not baseline_costs:
            return 100.0 if current_costs else 0.0

        # map by name
        base_by_name = {c.get("name"): c for c in baseline_costs}
        total = 0.0
        count = 0
        for cost in current_costs:
            b = base_by_name.get(cost.name)
            if not b:
                total += 1.0
                count += 1
                continue
            total += self._relative_delta(float(cost.fixed_time), float(b.get("fixed_time", 0.0)))
            total += self._relative_delta(float(cost.per_piece_time), float(b.get("per_piece_time", 0.0)))
            total += self._relative_delta(float(cost.hourly_rate), float(b.get("hourly_rate", 0.0)))
            total += self._relative_delta(float(cost.margin_rate), float(b.get("margin_rate", 0.0)))
            count += 4
        # penalty for removed baseline costs
        removed = [n for n in base_by_name.keys() if n not in {c.name for c in current_costs}]
        total += len(removed)
        count += len(removed)
        if count == 0:
            return 0.0
        return round(min(100.0, (total / count) * 100.0), 1)

    def record_project_template_usage(self, project):
        project_uuid = getattr(project, "mwq_uuid", None)
        if not project_uuid:
            return
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            for i, op in enumerate(project.operations):
                if not getattr(op, "template_id", None):
                    continue
                drift = float(getattr(op, "template_drift_score", 0.0) or 0.0)
                cur.execute(
                    "INSERT INTO project_template_usage (template_id, project_uuid, op_index, drift_score, used_at) "
                    "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (op.template_id, project_uuid, i, drift),
                )
            conn.commit()

    def create_initial_templates_from_ai_dataset(self, dataset_path: str) -> int:
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        projects = data.get("projects", [])

        by_typology = {}
        for p in projects:
            for op in p.get("operations", []):
                typ = (op.get("typology") or "").strip()
                if not typ:
                    continue
                by_typology.setdefault(typ, []).append(op)

        created = 0
        for typology, ops in by_typology.items():
            payload = self._build_median_template_payload(typology, ops)
            if not payload.get("costs"):
                continue
            with self.db.get_connection() as conn:
                cur = conn.cursor()
                now = datetime.now().isoformat(timespec="seconds")
                cur.execute(
                    "INSERT INTO operation_templates (name, typology, config_json, tags, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"Auto-{typology}", typology, json.dumps(payload, ensure_ascii=False), "auto,ai", now, now),
                )
                conn.commit()
                created += 1
        return created

    def _build_median_template_payload(self, typology: str, operations: list[dict]) -> dict:
        # flatten costs by cost_type then summarize medians
        grouped = {}
        for op in operations:
            for c in op.get("costs", []):
                ctype = c.get("cost_type")
                grouped.setdefault(ctype, []).append(c)

        costs = []
        for ctype, items in grouped.items():
            fixed_times = [float(x.get("internal_operation", {}).get("fixed_time_h", 0.0) or 0.0) for x in items]
            piece_times = [float(x.get("internal_operation", {}).get("per_piece_time_h", 0.0) or 0.0) for x in items]
            hourly_rates = [float(x.get("internal_operation", {}).get("hourly_rate", 0.0) or 0.0) for x in items]
            margins = [float(x.get("margin_rate", 0.0) or 0.0) for x in items]
            units = [x.get("pricing", {}).get("unit") for x in items if x.get("pricing", {}).get("unit")]

            costs.append({
                "name": f"{ctype} - standard",
                "cost_type": ctype,
                "pricing_type": "Par unité",
                "fixed_price": 0.0,
                "unit_price": 0.0,
                "unit": statistics.mode(units) if units else "pièce",
                "fixed_time": statistics.median(fixed_times) if fixed_times else 0.0,
                "per_piece_time": statistics.median(piece_times) if piece_times else 0.0,
                "hourly_rate": statistics.median(hourly_rates) if hourly_rates else 0.0,
                "margin_rate": statistics.median(margins) if margins else 0.0,
                "quantity_per_piece": 1.0,
                "quantity_per_piece_is_inverse": False,
                "comment": "",
            })

        return {"typology": typology, "operation_comment": "", "costs": costs}

    def _operation_to_template_payload(self, operation: Operation) -> dict:
        costs = []
        for cost in operation.costs.values():
            costs.append({
                "name": cost.name,
                "cost_type": cost.cost_type.value,
                "pricing_type": cost.pricing.pricing_type.value if cost.pricing else domain_cost.PricingType.PER_UNIT.value,
                "fixed_price": cost.pricing.fixed_price if cost.pricing else 0.0,
                "unit_price": cost.pricing.unit_price if cost.pricing else 0.0,
                "unit": cost.pricing.unit if cost.pricing else "pièce",
                "fixed_time": cost.fixed_time,
                "per_piece_time": cost.per_piece_time,
                "hourly_rate": cost.hourly_rate,
                "margin_rate": cost.margin_rate,
                "quantity_per_piece": cost.quantity_per_piece,
                "quantity_per_piece_is_inverse": bool(cost.quantity_per_piece_is_inverse),
                "comment": cost.comment or "",
            })
        return {
            "typology": operation.typology,
            "operation_comment": operation.comment or "",
            "costs": costs,
        }

    def _relative_delta(self, a: float, b: float) -> float:
        denom = max(abs(b), 1e-6)
        return min(1.0, abs(a - b) / denom)

    def _cost_type_from_value(self, value: str):
        for ct in domain_cost.CostType:
            if ct.value == value:
                return ct
        return domain_cost.CostType.INTERNAL_OPERATION

    def _pricing_type_from_value(self, value: str):
        for pt in domain_cost.PricingType:
            if pt.value == value:
                return pt
        return domain_cost.PricingType.PER_UNIT
