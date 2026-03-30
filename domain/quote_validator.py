from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.cost import CostType
from domain.operation import SUBCONTRACTING_TYPOLOGY


@dataclass
class ValidationWarning:
    code: str
    severity: str
    message: str
    context: dict[str, Any]


class QuoteValidator:
    """Independent rules engine for quote robustness diagnostics."""

    @staticmethod
    def validate(project) -> dict:
        warnings: list[ValidationWarning] = []
        max_qty = max(project.sale_quantities) if getattr(project, "sale_quantities", None) else 1

        # Rule 1: internal margin = 0
        for op in project.operations:
            for cost_name, cost in op.costs.items():
                if cost.cost_type == CostType.INTERNAL_OPERATION and (cost.margin_rate or 0.0) <= 0.0:
                    warnings.append(ValidationWarning(
                        code="MARGIN_ZERO_INTERNAL",
                        severity="medium",
                        message="Marge interne nulle sur une opération interne.",
                        context={"operation": op.label, "cost": cost_name},
                    ))

        # Rule 2: disproportionate fixed time
        for op in project.operations:
            for cost_name, cost in op.costs.items():
                if cost.cost_type != CostType.INTERNAL_OPERATION:
                    continue
                fixed_t = float(cost.fixed_time or 0.0)
                variable_t = float(cost.per_piece_time or 0.0) * max_qty
                if fixed_t > 0 and fixed_t > (3.0 * max(variable_t, 1e-6)):
                    warnings.append(ValidationWarning(
                        code="FIXED_TIME_DISPROPORTIONATE",
                        severity="medium",
                        message="Temps fixe très dominant vs temps pièce au volume max.",
                        context={"operation": op.label, "cost": cost_name, "fixed_time_h": fixed_t, "variable_time_h": variable_t},
                    ))

        # Rule 3: volume margin incoherence
        qtys = sorted(project.sale_quantities or [])
        rates = project.volume_margin_rates or {}
        missing_q = [q for q in qtys if q not in rates]
        invalid_q = [q for q in qtys if q in rates and float(rates[q]) <= 0]
        if missing_q or invalid_q:
            warnings.append(ValidationWarning(
                code="VOLUME_MARGIN_INCOHERENT",
                severity="high",
                message="Incohérences sur les coefficients de marge volume.",
                context={"missing_quantities": missing_q, "invalid_quantities": invalid_q},
            ))

        # Rule 4: inactive subcontracting line(s)
        for op in project.operations:
            if op.typology != SUBCONTRACTING_TYPOLOGY:
                continue
            sub_lines = [c for c in op.costs.values() if c.cost_type == CostType.SUBCONTRACTING]
            inactive_count = len([c for c in sub_lines if not c.is_active])
            active_count = len([c for c in sub_lines if c.is_active])
            if inactive_count > 0:
                warnings.append(ValidationWarning(
                    code="SUBCONTRACTING_INACTIVE_LINES",
                    severity="low",
                    message="Lignes sous-traitance inactives détectées.",
                    context={"operation": op.label, "inactive_count": inactive_count, "active_count": active_count},
                ))
            if len(sub_lines) > 0 and active_count == 0:
                warnings.append(ValidationWarning(
                    code="SUBCONTRACTING_NO_ACTIVE_LINE",
                    severity="high",
                    message="Aucune ligne sous-traitance active.",
                    context={"operation": op.label},
                ))

        # Rule 5: external cost without supplier signal
        for op in project.operations:
            for cost_name, cost in op.costs.items():
                if cost.cost_type not in (CostType.MATERIAL, CostType.SUBCONTRACTING):
                    continue
                pricing = cost.pricing
                total_price_signal = 0.0
                if pricing:
                    total_price_signal = float(pricing.fixed_price or 0.0) + float(pricing.unit_price or 0.0)
                has_supplier_ref = bool((cost.supplier_quote_ref or "").strip())
                has_docs = len(cost.documents or []) > 0
                if total_price_signal <= 0 and not has_supplier_ref and not has_docs:
                    warnings.append(ValidationWarning(
                        code="NO_SUPPLIER_SIGNAL",
                        severity="medium",
                        message="Coût achat/sous-traitance sans prix fournisseur ni référence ni document.",
                        context={"operation": op.label, "cost": cost_name},
                    ))

        # Score model
        weight = {"high": 25, "medium": 10, "low": 4}
        total_penalty = sum(weight.get(w.severity, 0) for w in warnings)
        robustness_score = max(0, 100 - total_penalty)
        risk_index = min(100, total_penalty)

        return {
            "score": robustness_score,
            "risk_index": risk_index,
            "warnings_count": len(warnings),
            "warnings": [
                {"code": w.code, "severity": w.severity, "message": w.message, "context": w.context}
                for w in warnings
            ],
        }
