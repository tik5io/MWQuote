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


# ---------------------------------------------------------------------------
# Temps nul = lancement pur ; étapes désactivables
# ---------------------------------------------------------------------------

def _internal(name, fixed_h=0.0, per_piece_h=0.0, rate=70.0):
    from domain.cost import CostItem, PricingStructure, PricingType
    return CostItem(name=name, cost_type=CostType.INTERNAL_OPERATION,
                    pricing=PricingStructure(PricingType.PER_UNIT),
                    fixed_time=fixed_h, per_piece_time=per_piece_h, hourly_rate=rate)


def _sd_and_ops(*ops):
    from domain.serie_data import SerieData
    sd = SerieData()
    project = types.SimpleNamespace(phases=[])
    sd.sync_from_project(project, operations=list(ops))
    return sd, project


def test_zero_time_operation_still_counts_for_launch():
    """Une opération sans temps de cycle (lancement pur) garde son temps et son coût de lancement."""
    from domain.operation import Operation
    op = Operation(code="OP1", label="Mise en route", typology="Interne")
    op.costs["Prépa"] = _internal("Prépa", fixed_h=0.5, per_piece_h=0.0, rate=70.0)
    sd, project = _sd_and_ops(op)
    sd.machine_posts[0].setup_launch_h = 2.0
    post = sd.machine_posts[0]
    assert post.cycle_time_s == 0
    assert post.mo_rate_euro_per_h == pytest.approx(70.0)       # taux de l'étape, plus 28 €/h par défaut
    assert sd.setup_launch_time_total_h() == pytest.approx(2.0)
    assert sd.setup_launch_cost_per_shift() == pytest.approx(140.0)


def test_disabled_step_is_excluded_from_cycle_time_and_setup():
    from domain.operation import Operation
    op = Operation(code="OP1", label="Op", typology="Interne")
    op.costs["A"] = _internal("A", fixed_h=1.0, per_piece_h=0.01, rate=100.0)    # 36 s / pièce
    op.costs["B"] = _internal("B", fixed_h=0.5, per_piece_h=0.005, rate=50.0)    # 18 s / pièce
    sd, project = _sd_and_ops(op)
    assert sd.machine_posts[0].cycle_time_s == pytest.approx(54.0)

    sd.disabled_step_keys = [sd.step_key("OP1", "B")]
    sd.setup_from_fixed_times = True
    sd.sync_from_project(project, operations=[op])
    assert sd.machine_posts[0].cycle_time_s == pytest.approx(36.0)
    assert sd.machine_posts[0].mo_rate_euro_per_h == pytest.approx(100.0)
    assert sd.synced_setup_time_h == pytest.approx(1.0)          # le réglage de B n'est plus compté

    sd.disabled_step_keys = []
    sd.sync_from_project(project, operations=[op])
    assert sd.machine_posts[0].cycle_time_s == pytest.approx(54.0)
    assert sd.synced_setup_time_h == pytest.approx(1.5)


def test_disabled_step_keys_survive_save_and_load():
    import os, tempfile
    from domain.operation import Operation
    from domain.phase import PhaseKind
    from domain.project import Project
    from infrastructure.persistence import PersistenceService
    op = Operation(code="OP1", label="Op", typology="Interne")
    op.costs["A"] = _internal("A", per_piece_h=0.01)
    p = Project(name="P", reference="R", client="C", operations=[op], sale_quantities=[1])
    v = p.add_version_variant("Série", PhaseKind.SERIE, annual_volume=1000)
    v.phase.serie_data.disabled_step_keys = ["OP1::A"]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "p.mwq")
        PersistenceService.save_project(p, path)
        q = PersistenceService.load_project(path)
    serie = [x for x in q.versions if x.is_serie][0]
    assert serie.phase.serie_data.disabled_step_keys == ["OP1::A"]


def test_grid_row_ignores_disabled_steps(row):
    r, a, b = row
    r.set_step_enabled("b", False)
    assert [s.label for s in r.active_steps] == ["Perçage"]
    assert r.tc0_s == pytest.approx(60.0)                 # le contrôle (30 s) sort de la base
    assert r.rate0 == pytest.approx(100.0)
    r.time_pct = 10
    assert id(b) not in r.overrides()                     # pas de simulation sur une étape désactivée
    assert r.tc_sim_s == pytest.approx(66.0)


def test_grid_row_with_zero_time_keeps_a_rate():
    """Opération de lancement pur : le curseur de taux reste utilisable (taux moyen des étapes)."""
    a, b = _cost("Prépa", 0.0, 80.0), _cost("Réglage", 0.0, 60.0)
    op = types.SimpleNamespace(code="OP", label="Lancement", costs={"a": a, "b": b})
    r = _OpSensRow(op)
    assert r.tc0_s == 0
    assert r.rate0 == pytest.approx(70.0)
    r.rate_pct = 10
    assert r.rate_sim == pytest.approx(77.0)
    assert r.overrides()[id(a)] == {"rate": pytest.approx(88.0)}
