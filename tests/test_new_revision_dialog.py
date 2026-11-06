"""Fenêtre « Créer un nouvel indice » : ajustement des coefficients d'une offre archivée."""
import pytest
import wx

from domain import offers


@pytest.fixture(scope="module")
def app():
    return wx.App(False)


def _lot(rates=None):
    return {"mode": "lot", "quantities": [1, 10], "rates": rates or {"1": 1.5, "10": 1.2}}


def _make(app, base, **kw):
    from ui.dialogs.new_revision_dialog import NewRevisionDialog
    return NewRevisionDialog(None, "OD260720_001", "B", base, from_revision="A", **kw)


def test_ok_disabled_until_a_coefficient_changes(app):
    d = _make(app, _lot(), lot_base_prices={1: 100.0, 10: 80.0})
    try:
        assert not d.ok_btn.IsEnabled()
        assert offers.same_coefficients(d.get_coefficients(), _lot())
        d._rows[0][1].SetValue(1.6)
        d._on_coef(0)
        assert d.ok_btn.IsEnabled()
    finally:
        d.Destroy()


def test_coefficient_and_price_are_linked(app):
    d = _make(app, _lot(), lot_base_prices={1: 100.0, 10: 80.0})
    try:
        q, coef, price, gap, orig = d._rows[0]
        assert price.GetValue() == pytest.approx(150.0)          # 100 × 1.5
        price.SetValue(180.0)
        d._on_price(0)
        assert coef.GetValue() == pytest.approx(1.8)             # prix visé → coefficient
        assert gap.GetLabel() == "+20.0 %"
        coef.SetValue(1.0)
        d._on_coef(0)
        assert price.GetValue() == pytest.approx(100.0)          # coefficient → prix
    finally:
        d.Destroy()


def test_new_coefficients_use_snapshot_format_and_keep_other_quantities(app):
    d = _make(app, _lot(), lot_base_prices={1: 100.0, 10: 80.0})
    try:
        d._rows[1][1].SetValue(1.1)
        d._on_coef(1)
        new = d.get_coefficients()
        assert new["mode"] == "lot" and new["quantities"] == [1, 10]
        assert new["rates"] == {"1": pytest.approx(1.5), "10": pytest.approx(1.1)}
        assert not offers.same_coefficients(_lot(), new)
    finally:
        d.Destroy()


def test_price_field_disabled_without_base_cost(app):
    d = _make(app, _lot(), lot_base_prices={1: 0.0, 10: 80.0})
    try:
        assert not d._rows[0][2].IsEnabled()                     # pas de coût de base : coefficient seul
        assert d._rows[1][2].IsEnabled()
    finally:
        d.Destroy()


def test_display_currency_conversion(app):
    d = _make(app, _lot(), lot_base_prices={1: 100.0, 10: 80.0}, fx=1.1, symbol="$")
    try:
        _q, coef, price, _g, _o = d._rows[0]
        assert price.GetValue() == pytest.approx(165.0)          # 100 × 1.5 × 1.1
        price.SetValue(198.0)
        d._on_price(0)
        assert coef.GetValue() == pytest.approx(1.8)             # le coefficient reste en devise de base
    finally:
        d.Destroy()


def test_serie_margin(app):
    base = {"mode": "serie", "annual_volume": 50000, "global_commercial_margin": 0.25}
    d = _make(app, base, serie_price_fn=lambda m: 10.0 * (1 + m))
    try:
        assert not d.ok_btn.IsEnabled()
        assert d.serie_price.GetLabel().startswith("12.50")
        d.margin.SetValue(30.0)
        d._update_state()
        new = d.get_coefficients()
        assert new["global_commercial_margin"] == pytest.approx(0.30)
        assert new["annual_volume"] == 50000                      # le volume n'est pas un coefficient
        assert d.ok_btn.IsEnabled()
        assert d.serie_price.GetLabel().startswith("13.00")
    finally:
        d.Destroy()
