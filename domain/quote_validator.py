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


def _phase_items(project):
    """[(op, {clé: ligne})] de la version courante."""
    return [(op, dict(op.costs)) for op in project.operations]


class QuoteValidator:
    """Independent rules engine for quote robustness diagnostics.

    Les règles 1 à 5 portent sur la phase active ; les règles de phases
    (cohérence Proto / Série) portent sur toute la version.
    """

    @staticmethod
    def phase_warnings(project) -> list:
        """Cohérence de la version courante : pièces fournies avec l'outillage vs prix pièce."""
        from domain.phase import PhaseKind
        warnings: list[ValidationWarning] = []
        version = getattr(project, "current_version", None)
        if version is None:
            return warnings
        phase = version.phase
        purchase_types = (CostType.MATERIAL, CostType.SUBCONTRACTING)

        for op in version.operations:
            for c in op.costs.values():
                if c.cost_type not in purchase_types or not c.pricing:
                    continue
                if op.typology == SUBCONTRACTING_TYPOLOGY and not c.is_active:
                    continue
                has_price = (c.pricing.unit_price or 0) > 0 or any(
                    (t.unit_price or 0) > 0 for t in (c.pricing.tiers or []))
                included = op.free_pieces_for(c)
                if has_price or included <= 0:
                    continue
                if phase.kind == PhaseKind.LOT:
                    beyond = [q for q in phase.sale_quantities if q > included]
                    if beyond:
                        warnings.append(ValidationWarning(
                            code="PRICE_MISSING_BEYOND_INCLUDED",
                            severity="high",
                            message=(f"« {op.label} › {c.name} » : {included} pièces incluses avec l'outillage, "
                                     f"mais aucun prix pièce au-delà (quantités {', '.join(map(str, beyond))})."),
                            context={"operation": op.label, "cost": c.name, "included": included,
                                     "phase": phase.display_label},
                        ))
                else:
                    warnings.append(ValidationWarning(
                        code="PRICE_MISSING_BEYOND_INCLUDED",
                        severity="high",
                        message=(f"« {op.label} › {c.name} » : aucun prix pièce en "
                                 f"{phase.display_label} au-delà des {included} pièces incluses."),
                        context={"operation": op.label, "cost": c.name, "included": included,
                                 "phase": phase.display_label},
                    ))
        return warnings

    @staticmethod
    def validate(project) -> dict:
        warnings: list[ValidationWarning] = []
        max_qty = max(project.sale_quantities) if getattr(project, "sale_quantities", None) else 1
        phase_items = _phase_items(project)

        # Rule 1: internal margin = 0
        for op, costs in phase_items:
            for cost_name, cost in costs.items():
                if cost.cost_type == CostType.INTERNAL_OPERATION and (cost.margin_rate or 0.0) <= 0.0:
                    warnings.append(ValidationWarning(
                        code="MARGIN_ZERO_INTERNAL",
                        severity="medium",
                        message="Marge interne nulle sur une opération interne.",
                        context={"operation": op.label, "cost": cost_name},
                    ))

        # Rule 2: disproportionate fixed time
        for op, costs in phase_items:
            for cost_name, cost in costs.items():
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
        for op, costs in phase_items:
            if op.typology != SUBCONTRACTING_TYPOLOGY:
                continue
            sub_lines = [c for c in costs.values() if c.cost_type == CostType.SUBCONTRACTING]
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
        for op, costs in phase_items:
            for cost_name, cost in costs.items():
                if cost.cost_type not in (CostType.MATERIAL, CostType.SUBCONTRACTING):
                    continue
                pricing = cost.pricing
                total_price_signal = 0.0
                if pricing:
                    total_price_signal = float(pricing.fixed_price or 0.0) + float(pricing.unit_price or 0.0)
                has_supplier_ref = bool((cost.supplier_quote_ref or "").strip())
                has_docs = len(cost.documents or []) > 0
                total_price_signal += float(getattr(cost, "tooling_amount", 0.0) or 0.0)
                # Outillage rattaché à l'offre (ou commun à l'opération) = signal fournisseur
                total_price_signal += sum(
                    float(t.pricing.fixed_price or 0.0) for t in op.costs.values()
                    if t.cost_type == CostType.TOOLING and t.pricing
                    and t.linked_offer in (None, "", cost.name))
                if total_price_signal <= 0 and not has_supplier_ref and not has_docs:
                    warnings.append(ValidationWarning(
                        code="NO_SUPPLIER_SIGNAL",
                        severity="medium",
                        message="Coût achat/sous-traitance sans prix fournisseur ni référence ni document.",
                        context={"operation": op.label, "cost": cost_name},
                    ))

        # Cohérence entre phases (Proto / Série)
        if hasattr(project, "current_version"):
            warnings.extend(QuoteValidator.phase_warnings(project))

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
