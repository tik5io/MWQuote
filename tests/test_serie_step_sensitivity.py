"""Décomposé : déplier une opération en étapes et ajuster temps / taux étape par étape."""
import types

import pytest

from domain.cost import CostType
from ui.panels.serie_pricing_panel import _OpSensRow


def _cost(name, cycle_s, rate):
    """Ligne interne factice : 1 pièce / cycle, sans parallélisme."""
    c = types.SimpleNamespace(name=name, cost_type=CostType.INTERNAL_OPERATION, is_active=True,
                              serie_cycle_time_s=cycle_s, serie_hourly_rate=rate)
    c.serie_cycle_s = lambda: c.serie_cycle_time_s
    c.serie_rate = lambda: c.serie_hourly_rate
    c.serie_time_per_piece_h = lambda: c.serie_cycle_time_s / 3600.0
    return c


@pytest.fixture
def row():
    a, b = _cost("Perçage", 60.0, 100.0), _cost("Contrôle", 30.0, 50.0)
    op = types.SimpleNamespace(code="OP10", label="Perçage D1", costs={"a": a, "b": b})
    return _OpSensRow(op), a, b


def test_one_step_per_internal_line(row):
    r, a, b = row
    assert [s.label for s in r.steps] == ["Perçage", "Contrôle"]
    assert r.tc0_s == pytest.approx(90.0)
    assert r.rate0 == pytest.approx((60 * 100 + 30 * 50) / 90)   # moyenne pondérée par le temps


def test_without_step_adjustment_behaves_like_before(row):
    """Curseurs d'opération seuls : mêmes résultats que l'ancien comportement (échelle uniforme)."""
    r, a, b = row
    r.time_pct, r.rate_pct = 10, -20
    assert r.tc_sim_s == pytest.approx(r.tc0_s * 1.10)
    assert r.rate_sim == pytest.approx(r.rate0 * 0.80)
    ov = r.overrides()
    assert ov[id(a)] == {"cycle_s": pytest.approx(66.0), "rate": pytest.approx(80.0)}
    assert ov[id(b)] == {"cycle_s": pytest.approx(33.0), "rate": pytest.approx(40.0)}


def test_step_adjustment_touches_only_that_step(row):
    r, a, b = row
    r.steps[0].time_pct = 50                  # Perçage +50 % de temps
    assert r.moved and not r.op_moved
    ov = r.overrides()
    assert id(b) not in ov                    # Contrôle intact
    assert ov[id(a)] == {"cycle_s": pytest.approx(90.0)}
    assert r.tc_sim_s == pytest.approx(90.0 + 30.0)
    # le taux simulé agrégé suit la pondération par les nouveaux temps
    assert r.rate_sim == pytest.approx((90 * 100 + 30 * 50) / 120)


def test_step_and_operation_factors_combine(row):
    r, a, b = row
    r.time_pct = 10
    r.steps[1].time_pct = -50                 # Contrôle : ×1.10 × 0.50
    ov = r.overrides()
    assert ov[id(a)] == {"cycle_s": pytest.approx(66.0)}
    assert ov[id(b)] == {"cycle_s": pytest.approx(30.0 * 1.10 * 0.50)}
    assert r.steps[1].tc_sim_s == pytest.approx(16.5)


def test_apply_writes_serie_values_per_step(row):
    r, a, b = row
    r.steps[0].rate_pct = 25
    r.apply()
    assert a.serie_hourly_rate == pytest.approx(125.0)
    assert b.serie_hourly_rate == pytest.approx(50.0)       # inchangé
    assert a.serie_cycle_time_s == pytest.approx(60.0)


def test_rebind_keeps_step_adjustments(row):
    r, a, b = row
    r.steps[0].time_pct = 20
    a2, b2 = _cost("Perçage", 60.0, 100.0), _cost("Contrôle", 30.0, 50.0)
    r.bind(types.SimpleNamespace(code="OP10", label="Perçage D1", costs={"a": a2, "b": b2}))
    assert r.steps[0].time_pct == 20 and r.steps[1].time_pct == 0
    assert id(a2) in r.overrides()


def test_no_internal_step_means_nothing_to_unfold():
    op = types.SimpleNamespace(code="OP", label="ST", costs={})
    r = _OpSensRow(op)
    assert r.steps == [] and not r.moved and r.tc_sim_s == 0
