import json
import os
import tempfile
import unittest
import zipfile

from domain.cost import CostItem, CostType, PricingStructure, PricingType
from domain.operation import Operation
from domain.phase import PhaseKind, ToolingBilling
from domain.project import Project
from domain.serie_data import SerieData
from infrastructure.persistence import PersistenceService


def _internal(name, fixed_h=1.0, per_piece_h=0.01, rate=100.0):
    c = CostItem(name=name, cost_type=CostType.INTERNAL_OPERATION,
                 pricing=PricingStructure(PricingType.PER_UNIT),
                 fixed_time=fixed_h, per_piece_time=per_piece_h, hourly_rate=rate)
    return c


def _tool(name, amount, billing=None):
    c = CostItem(name=name, cost_type=CostType.TOOLING,
                 pricing=PricingStructure(PricingType.PER_UNIT, fixed_price=amount))
    c.tooling_billing = billing
    return c


def _subcontract(name, unit_price, tooling=0.0, included=0, active=True):
    c = CostItem(name=name, cost_type=CostType.SUBCONTRACTING,
                 pricing=PricingStructure(PricingType.PER_UNIT, unit_price=unit_price))
    c.tooling_amount = tooling
    c.tooling_included_pieces = included
    c.is_active = active
    return c


def _project():
    op = Operation(code="OP1", label="Découpe", typology="Microdécoupe")
    op.costs["Découpe"] = _internal("Découpe")
    op.costs["Outil"] = _tool("Outil", 1000.0)
    return Project(name="P", reference="REF", client="C", operations=[op],
                   sale_quantities=[10, 100], volume_margin_rates={10: 1.2, 100: 1.1})


class LegacyConversionTest(unittest.TestCase):
    def test_project_without_serie_has_a_single_taux_horaire_version(self):
        p = _project()
        self.assertEqual(len(p.versions), 1)
        self.assertEqual(len(p.phases), 1)
        self.assertEqual(p.current_phase.kind, PhaseKind.LOT)
        self.assertEqual(p.sale_quantities, [10, 100])
        self.assertEqual(p.volume_margin_rates, {10: 1.2, 100: 1.1})
        self.assertIsNone(p.serie_data)

    def test_legacy_serie_data_becomes_a_separate_decompose_version(self):
        sd = SerieData(annual_volume=12345)
        p = Project(name="P", reference="R", client="C", serie_data=sd,
                    operations=[Operation(code="OP", label="X", typology="Interne")])
        self.assertEqual([v.phase.kind for v in p.versions], [PhaseKind.LOT, PhaseKind.SERIE])
        self.assertEqual([v.version_index for v in p.versions], [1, 2])
        self.assertIsNone(p.serie_data)            # V1 = Taux horaire
        p.switch_to_version(2)
        self.assertIs(p.serie_data, sd)
        self.assertFalse(sd.sync_purchases)        # ancien chiffrage série : pas de sync automatique
        self.assertIsNot(p.versions[0].operations[0], p.versions[1].operations[0])  # gamme copiée

    def test_prices_unchanged_without_phase_tags(self):
        p = _project()
        # 1h fixe + 0.01h/pc à 100€/h ; outillage refacturé hors prix pièce
        self.assertAlmostEqual(p.total_price(10), (100 + 10) / 10 * 1.2)
        self.assertAlmostEqual(p.total_price(100), (100 + 100) / 100 * 1.1)


class VersionConfigTest(unittest.TestCase):
    """Une version = une gamme + un mode de calcul + des quantités."""

    def test_variant_copies_the_range_and_changes_the_mode(self):
        p = _project()
        v2 = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=50000)
        self.assertEqual((v2.version_index, v2.created_from_version), (2, 1))
        self.assertEqual(v2.phase.kind, PhaseKind.SERIE)
        self.assertEqual(v2.serie_data.annual_volume, 50000)
        self.assertTrue(v2.serie_data.sync_purchases)
        self.assertIsNot(v2.operations[0], p.versions[0].operations[0])
        # la version d'origine n'a pas bougé
        self.assertEqual(p.versions[0].phase.kind, PhaseKind.LOT)
        self.assertEqual(p.versions[0].sale_quantities, [10, 100])
        self.assertEqual(p.versions[0].describe(), "Taux horaire · 10 / 100 pc")
        self.assertEqual(v2.describe(), "Décomposé · 50 000 / an")

    def test_variant_with_other_quantities(self):
        p = _project()
        v2 = p.add_version_variant("Gros lots", PhaseKind.LOT, sale_quantities=[5000, 1000, 1000])
        p.switch_to_version(v2.version_index)
        self.assertEqual(p.sale_quantities, [1000, 5000])
        p.switch_to_version(1)
        self.assertEqual(p.sale_quantities, [10, 100])

    def test_decompose_version_exposes_annual_volume_as_its_quantity(self):
        p = _project()
        v2 = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=80000)
        self.assertEqual(v2.sale_quantities, [80000])

    def test_decompose_data_cannot_be_attached_to_a_taux_horaire_version(self):
        p = _project()
        with self.assertRaises(ValueError):
            p.serie_data = SerieData()

    def test_new_version_is_an_independent_copy(self):
        p = _project()
        v2 = p.add_version("V2")
        v2.operations[0].costs["Découpe"].hourly_rate = 999.0
        v2.phase.sale_quantities.append(7)
        self.assertEqual(p.versions[0].operations[0].costs["Découpe"].hourly_rate, 100.0)
        self.assertEqual(p.versions[0].phase.sale_quantities, [10, 100])


class DecomposeFromBaseVersionTest(unittest.TestCase):
    """Version Décomposé : on choisit la version Taux horaire de départ ; temps copiés, lien rompu."""

    def _project_with_two_versions(self):
        p = _project()                                   # V1 : Découpe 0.01 h/pc à 100 €/h
        v2 = p.add_version("V2")
        v2.operations[0].costs["Découpe"].per_piece_time = 0.05      # V2 : temps très différent
        p.switch_to_version(v2.version_index)            # la version COURANTE est V2
        return p

    def test_base_version_is_the_chosen_one_not_the_current(self):
        p = self._project_with_two_versions()
        v3 = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=10000, base_version_index=1)
        self.assertEqual(v3.created_from_version, 1)
        self.assertEqual(v3.operations[0].costs["Découpe"].per_piece_time, 0.01)       # temps de V1
        post = v3.serie_data.machine_posts[0]
        self.assertAlmostEqual(post.cycle_time_s, 0.01 * 3600)                          # temps repris à la création
        self.assertAlmostEqual(post.mo_rate_euro_per_h, 100.0)

    def test_default_base_is_the_current_version(self):
        p = self._project_with_two_versions()
        v3 = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=10000)
        self.assertEqual(v3.created_from_version, 2)
        self.assertAlmostEqual(v3.serie_data.machine_posts[0].cycle_time_s, 0.05 * 3600)

    def test_link_with_the_base_is_broken_after_creation(self):
        p = self._project_with_two_versions()
        v3 = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=10000, base_version_index=1)
        p.versions[0].operations[0].costs["Découpe"].per_piece_time = 0.5      # on retouche V1 ensuite
        p.versions[0].operations[0].costs["Découpe"].hourly_rate = 999.0
        self.assertEqual(v3.operations[0].costs["Découpe"].per_piece_time, 0.01)
        post = v3.serie_data.machine_posts[0]
        self.assertAlmostEqual(post.cycle_time_s, 36.0)
        self.assertAlmostEqual(post.mo_rate_euro_per_h, 100.0)

    def test_unknown_base_falls_back_to_current(self):
        p = self._project_with_two_versions()
        v3 = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=1000, base_version_index=99)
        self.assertEqual(v3.created_from_version, 2)


class ToolingBillingRuleTest(unittest.TestCase):
    def test_taux_horaire_never_amortizes_tooling(self):
        p = _project()
        base = p.total_price(10)
        p.current_phase.tooling_billing = ToolingBilling.AMORTIZED
        self.assertAlmostEqual(p.total_price(10), base)  # outil hors prix pièce
        self.assertEqual([t.name for t in p.operations[0].get_reinvoiced_tooling_costs()], ["Outil"])

    def test_line_override_only_applies_in_decompose(self):
        p = _project()
        p.operations[0].costs["Outil"].tooling_billing = ToolingBilling.AMORTIZED
        op = p.operations[0]
        self.assertEqual([t.name for t in op.get_reinvoiced_tooling_costs()], ["Outil"])
        self.assertEqual(op.get_amortized_tooling_costs(), [])
        v2 = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=1000)
        p.switch_to_version(v2.version_index)
        op = p.operations[0]
        self.assertEqual(op.get_reinvoiced_tooling_costs(), [])
        self.assertEqual(len(op.get_amortized_tooling_costs()), 1)


class VersionPersistenceTest(unittest.TestCase):
    def test_roundtrip_versions_and_v30_mirror(self):
        p = _project()
        expected = p.total_price(10)
        v2 = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=500000)
        p.switch_to_version(v2.version_index)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            PersistenceService.save_project(p, path)
            with zipfile.ZipFile(path) as zf:
                data = json.loads(zf.read("project.json").decode("utf-8"))
            self.assertEqual(data["_mwq_version"], "3.3")
            v1d, v2d = data["versions"]
            # Miroir lisible par les anciens postes : quantités / coefficients du Taux horaire
            self.assertEqual(v1d["sale_quantities"], [10, 100])
            self.assertEqual(v1d["volume_margin_rates"], {"10": 1.2, "100": 1.1})
            self.assertIsNone(v1d["serie_data"])
            self.assertEqual(v2d["serie_data"]["annual_volume"], 500000)
            self.assertEqual([len(v["phases"]) for v in data["versions"]], [1, 1])
            q = PersistenceService.load_project(path)
        self.assertEqual([v.version_index for v in q.versions], [1, 2])
        self.assertEqual([v.phase.kind for v in q.versions], [PhaseKind.LOT, PhaseKind.SERIE])
        self.assertEqual(q.current_version_index, 2)
        self.assertEqual(q.serie_data.annual_volume, 500000)
        self.assertTrue(q.serie_data.sync_purchases)
        q.switch_to_version(1)
        self.assertEqual(q.volume_margin_rates, {10: 1.2, 100: 1.1})
        self.assertAlmostEqual(q.total_price(10), expected)


def _craft_file(path, mutate):
    """Écrit un .mwq d'un ancien format : on part d'un fichier courant et on le fait dériver."""
    PersistenceService.save_project(_project(), path)
    with zipfile.ZipFile(path) as zf:
        data = json.loads(zf.read("project.json").decode("utf-8"))
    mutate(data)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("project.json", json.dumps(data))


class LegacySplitMigrationTest(unittest.TestCase):
    """Conversion des anciens fichiers : une version par phase, sans toucher aux chiffres Taux horaire."""

    def test_v30_file_with_serie_data_splits_into_two_versions(self):
        def to_v30(data):
            data["_mwq_version"] = "3.0"
            data["export_history"] = [
                {"devis_ref": "A", "version_index": 1, "is_serie": False},
                {"devis_ref": "B", "version_index": 1, "is_serie": True},
            ]
            for v in data["versions"]:
                v.pop("phases"), v.pop("current_phase_id")
                v["serie_data"] = {"annual_volume": 250000}

        reference = _project()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            _craft_file(path, to_v30)
            q = PersistenceService.load_project(path)
            PersistenceService.save_project(q, path)       # réécriture au format courant
            r = PersistenceService.load_project(path)

        for project in (q, r):
            self.assertEqual([v.version_index for v in project.versions], [1, 2])
            v1, v2 = project.versions
            self.assertEqual((v1.phase.kind, v1.sale_quantities), (PhaseKind.LOT, [10, 100]))
            self.assertEqual((v2.phase.kind, v2.label, v2.created_from_version),
                             (PhaseKind.SERIE, "Série", 1))
            self.assertEqual(v2.serie_data.annual_volume, 250000)
            self.assertFalse(v2.serie_data.sync_purchases)     # chiffrage série historique inchangé
            self.assertEqual(len(v2.operations), len(v1.operations))
            # Taux horaire : strictement les mêmes prix qu'avant la conversion
            self.assertAlmostEqual(project.total_price(10), reference.total_price(10))
            self.assertAlmostEqual(project.total_price(100), reference.total_price(100))
        # L'offre série est rattachée à la version Décomposé, l'autre reste sur V1
        self.assertEqual({e["devis_ref"]: e["version_index"] for e in q.export_history}, {"A": 1, "B": 2})

    def test_v31_multi_phase_file_splits_and_drops_tags(self):
        def to_multi_phase(data):
            v = data["versions"][0]
            lot = v["phases"][0]
            serie = {"phase_id": "ph2", "label": "Pré-série", "kind": "Série", "sale_quantities": [],
                     "volume_margin_rates": {}, "tooling_billing": None,
                     "serie_data": {"annual_volume": 1000}}
            v["phases"] = [lot, serie]
            ops = v["operations"][0]["costs"]
            ops["Découpe"]["phases"] = ["ph1"]
            ops["Découpe série"] = dict(ops["Découpe"], name="Découpe série", phases=["ph2"], per_piece_time=0.001)
            data["export_history"] = [{"devis_ref": "S", "version_index": 1, "phase_id": "ph2", "is_serie": True}]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            _craft_file(path, to_multi_phase)
            q = PersistenceService.load_project(path)

        v1, v2 = q.versions
        self.assertEqual(sorted(v1.operations[0].costs), ["Découpe", "Outil"])
        self.assertEqual(sorted(v2.operations[0].costs), ["Découpe série", "Outil"])
        for v in q.versions:   # les tags de phase n'existent plus dans le modèle
            self.assertFalse(hasattr(v.operations[0], "phases"))
            self.assertFalse(any(hasattr(c, "phases") for c in v.operations[0].costs.values()))
        self.assertEqual(v2.label, "Pré-série")
        self.assertEqual(q.export_history[0]["version_index"], 2)
        self.assertAlmostEqual(q.total_price(10), _project().total_price(10))

    def test_written_file_carries_no_phase_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            PersistenceService.save_project(_project(), path)
            with zipfile.ZipFile(path) as zf:
                data = json.loads(zf.read("project.json").decode("utf-8"))
        for op in data["versions"][0]["operations"]:
            self.assertNotIn("phases", op)
            self.assertTrue(all("phases" not in c for c in op["costs"].values()))

    def test_single_phase_file_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            PersistenceService.save_project(_project(), path)
            q = PersistenceService.load_project(path)
        self.assertEqual(len(q.versions), 1)
        self.assertEqual(sorted(q.operations[0].costs), ["Découpe", "Outil"])


class SafeSaveTest(unittest.TestCase):
    def _write_v30_file(self, path):
        """Fabrique un fichier au format 3.0 (sans phases)."""
        PersistenceService.save_project(_project(), path)
        with zipfile.ZipFile(path) as zf:
            data = json.loads(zf.read("project.json").decode("utf-8"))
        data["_mwq_version"] = "3.0"
        for v in data["versions"]:
            v.pop("phases"), v.pop("current_phase_id")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("project.json", json.dumps(data))

    def test_v30_file_is_backed_up_once_before_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = PersistenceService.BACKUP_ROOT
            PersistenceService.BACKUP_ROOT = os.path.join(tmp, "backups")
            try:
                path = os.path.join(tmp, "p.mwq")
                self._write_v30_file(path)
                with open(path, "rb") as fh:
                    original = fh.read()
                p = PersistenceService.load_project(path)
                self.assertEqual(p.sale_quantities, [10, 100])
                PersistenceService.save_project(p, path)
                backup = os.path.join(tmp, "backups", "format-3.0", "p.mwq")
                with open(backup, "rb") as fh:
                    self.assertEqual(fh.read(), original)
                self.assertEqual(PersistenceService.read_file_format_version(path), "3.3")
                # Une nouvelle sauvegarde n'écrase pas la copie d'origine
                PersistenceService.save_project(p, path)
                with open(backup, "rb") as fh:
                    self.assertEqual(fh.read(), original)
                self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(tmp)))
            finally:
                PersistenceService.BACKUP_ROOT = old_root

    def test_failed_write_keeps_original_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            PersistenceService.save_project(_project(), path)
            with open(path, "rb") as fh:
                original = fh.read()
            broken = _project()
            broken.operations[0].costs["Découpe"].pricing = object()  # non sérialisable
            with self.assertRaises(Exception):
                PersistenceService.save_project(broken, path)
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), original)
            self.assertEqual(os.listdir(tmp), ["p.mwq"])


class SupplierToolingTest(unittest.TestCase):
    """Cas Stüken : outil fournisseur 19 400 € avec 500 pièces incluses."""

    def setUp(self):
        op = Operation(code="Sous-traitance", label="Ogive", typology="Sous-traitance")
        op.costs["Stueken"] = _subcontract("Stueken", unit_price=10.0, tooling=19400.0, included=500)
        op.costs["Autre"] = _subcontract("Autre", unit_price=50.0, tooling=5000.0, active=False)
        self.p = Project(name="P", reference="R", client="C", operations=[op], sale_quantities=[500, 600])

    def test_included_pieces_are_free_and_tooling_is_reinvoiced(self):
        self.assertAlmostEqual(self.p.total_price(500), 0.0)
        self.assertAlmostEqual(self.p.total_price(600), 100 * 10.0 / 600)
        tools = self.p.operations[0].get_reinvoiced_tooling_costs()
        self.assertEqual([(t.name, t.pricing.fixed_price) for t in tools], [("Outillage Stueken", 19400.0)])

    def test_supplier_tooling_stays_reinvoiced_in_taux_horaire(self):
        # « Amorti » est sans effet en Taux horaire : l'outil reste refacturé.
        self.p.operations[0].costs["Stueken"].tooling_billing = ToolingBilling.AMORTIZED
        self.assertAlmostEqual(self.p.total_price(500), 0.0)  # 500 pièces fournies gratuites
        tools = self.p.operations[0].get_reinvoiced_tooling_costs()
        self.assertEqual([(t.name, t.pricing.fixed_price) for t in tools], [("Outillage Stueken", 19400.0)])

    def test_supplier_tooling_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            PersistenceService.save_project(self.p, path)
            q = PersistenceService.load_project(path)
        # L'outillage fournisseur est migré en ligne Outillage rattachée à l'offre
        op = q.operations[0]
        c = op.costs["Stueken"]
        self.assertEqual((c.tooling_amount, c.tooling_included_pieces), (0.0, 0))
        tool = op.costs["Outillage Stueken"]
        self.assertEqual((tool.cost_type, tool.pricing.fixed_price, tool.tooling_included_pieces, tool.linked_offer),
                         (CostType.TOOLING, 19400.0, 500, "Stueken"))
        # Chiffres identiques : 500 pièces gratuites, outil refacturé, offre « Autre » inactive ignorée
        self.assertAlmostEqual(q.total_price(500), 0.0)
        self.assertAlmostEqual(q.total_price(600), self.p.total_price(600))
        self.assertEqual([(t.name, t.pricing.fixed_price) for t in op.get_reinvoiced_tooling_costs()],
                         [("Outillage Stueken", 19400.0)])

    def test_free_pieces_follow_tooling_line(self):
        op = Operation(code="OP", label="Pièce", typology="Sous-traitance")
        op.costs["Offre"] = _subcontract("Offre", unit_price=10.0)
        tool = _tool("Outil", 5000.0)
        tool.tooling_included_pieces = 200
        op.costs["Outil"] = tool
        p = Project(name="P", reference="R", client="C", operations=[op], sale_quantities=[200, 300])
        self.assertAlmostEqual(p.total_price(200), 0.0)             # 200 pièces comprises avec l'outil
        self.assertAlmostEqual(p.total_price(300), 100 * 10.0 / 300)  # au-delà : prix pièce
        # Outil rattaché à une offre inactive : ni gratuité ni refacturation
        op.costs["Offre"].is_active = False
        op.costs["Offre B"] = _subcontract("Offre B", unit_price=20.0)
        tool.linked_offer = "Offre"
        self.assertAlmostEqual(p.total_price(200), 200 * 20.0 / 200)
        self.assertEqual(op.get_reinvoiced_tooling_costs(), [])

    def test_linked_offer_follows_rename(self):
        op = Operation(code="OP", label="Pièce", typology="Sous-traitance")
        op.costs["Offre"] = _subcontract("Offre", unit_price=10.0)
        tool = _tool("Outil", 100.0)
        tool.linked_offer = "Offre"
        op.costs["Outil"] = tool
        op.rename_cost("Offre", "Offre Stüken")
        self.assertEqual(tool.linked_offer, "Offre Stüken")


class ToolingLinesTest(unittest.TestCase):
    def test_lines_sum_into_tooling_amount_and_roundtrip(self):
        from domain.cost import ToolingLine
        p = _project()
        tool = p.operations[0].costs["Outil"]
        tool.tooling_lines = [
            ToolingLine("Réglage FU10", 1, "h", 150.0),
            ToolingLine("Programme", 10, "h", 150.0),
            ToolingLine("Posage", 1, "forfait", 500.0),
        ]
        tool.apply_tooling_lines()
        self.assertAlmostEqual(tool.pricing.fixed_price, 2150.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            PersistenceService.save_project(p, path)
            q = PersistenceService.load_project(path)
        qt = q.operations[0].costs["Outil"]
        self.assertEqual([(l.label, l.quantity, l.unit, l.unit_price) for l in qt.tooling_lines],
                         [("Réglage FU10", 1, "h", 150.0), ("Programme", 10, "h", 150.0), ("Posage", 1, "forfait", 500.0)])
        self.assertAlmostEqual(qt.pricing.fixed_price, 2150.0)

    def test_tooling_without_lines_keeps_manual_amount(self):
        tool = _tool("Outil", 1000.0)
        tool.apply_tooling_lines()
        self.assertEqual(tool.pricing.fixed_price, 1000.0)


class PhaseCalcRulesTest(unittest.TestCase):
    def test_calc_labels(self):
        self.assertEqual(PhaseKind.LOT.calc_label, "Taux horaire")
        self.assertEqual(PhaseKind.SERIE.calc_label, "Décomposé")

    def test_lot_billing_always_reinvoiced(self):
        from domain.phase import Phase
        lot = Phase(phase_id="ph1", label="L", kind=PhaseKind.LOT,
                    tooling_billing=ToolingBilling.AMORTIZED)
        self.assertEqual(lot.effective_tooling_billing, ToolingBilling.REINVOICED)
        serie = Phase(phase_id="ph2", label="S", kind=PhaseKind.SERIE,
                      tooling_billing=ToolingBilling.AMORTIZED)
        self.assertEqual(serie.effective_tooling_billing, ToolingBilling.AMORTIZED)


class CleanModelConversionTest(unittest.TestCase):
    """Réorg catégories : typologie → {Interne, Sous-traitance}, famille conservée,
    lignes Matière inchangées (le MOQ ne s'applique qu'à la Sous-traitance)."""

    def _material(self, name, unit_price):
        return CostItem(name=name, cost_type=CostType.MATERIAL,
                        pricing=PricingStructure(PricingType.PER_UNIT, unit_price=unit_price))

    def test_typology_normalized_family_kept_prices_unchanged(self):
        from domain.operation import INTERNAL_TYPOLOGY, SUBCONTRACTING_TYPOLOGY
        op = Operation(code="OP1", label="Découpe", typology="Microdécoupe")
        op.costs["Matière"] = self._material("Matière", 3.0)
        op.costs["Usinage"] = _internal("Usinage", fixed_h=1.0, per_piece_h=0.0, rate=100.0)
        sub = Operation(code="OP2", label="Ogive", typology="Sous-traitance")
        sub.costs["Offre"] = _subcontract("Offre", unit_price=10.0)
        p = Project(name="P", reference="R", client="C", operations=[op, sub],
                    sale_quantities=[10], volume_margin_rates={10: 1.0})
        price_before = p.total_price(10)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            PersistenceService.save_project(p, path)
            self.assertEqual(PersistenceService.read_file_format_version(path), "3.3")
            q = PersistenceService.load_project(path)

        qop, qsub = q.operations
        self.assertEqual(qop.typology, INTERNAL_TYPOLOGY)          # « Microdécoupe » → Interne
        self.assertEqual(qop.family, "Microdécoupe")               # la famille n'est pas perdue
        self.assertEqual(qop.display_family, "Microdécoupe")
        self.assertEqual(qsub.typology, SUBCONTRACTING_TYPOLOGY)
        self.assertEqual(qop.costs["Matière"].cost_type, CostType.MATERIAL)  # pas de conversion de type
        self.assertAlmostEqual(q.total_price(10), price_before)

    def test_material_below_moq_price_is_preserved(self):
        """Matière à échelons sous son 1er palier : pas de MOQ (réservé à la Sous-traitance)."""
        from domain.cost import PricingTier
        op = Operation(code="OP1", label="Matière", typology="Matière")
        mat = CostItem(name="Barre", cost_type=CostType.MATERIAL,
                       pricing=PricingStructure(PricingType.TIERED,
                                                tiers=[PricingTier(100, 2.0), PricingTier(1000, 1.0)]))
        op.costs["Barre"] = mat
        p = Project(name="P", reference="R", client="C", operations=[op], sale_quantities=[10, 500])
        before = {q: p.total_price(q) for q in (10, 500)}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            PersistenceService.save_project(p, path)
            q = PersistenceService.load_project(path)
        for qty, price in before.items():
            self.assertAlmostEqual(q.total_price(qty), price)

    def test_conversion_is_idempotent(self):
        from domain.operation import INTERNAL_TYPOLOGY
        op = Operation(code="OP1", label="X", typology="Tournage")
        p = Project(name="P", reference="R", client="C", operations=[op], sale_quantities=[1])
        PersistenceService.convert_project_to_clean_model(p)
        PersistenceService.convert_project_to_clean_model(p)
        self.assertEqual((p.operations[0].typology, p.operations[0].family), (INTERNAL_TYPOLOGY, "Tournage"))


class SerieSyncTest(unittest.TestCase):
    def _project_with_serie(self, legacy=False):
        op = Operation(code="Microdécoupe", label="Découpe", typology="Interne")
        op.costs["Découpe"] = _internal("Découpe", fixed_h=2.0, per_piece_h=0.01, rate=100.0)
        op.costs["Outil"] = _tool("Outil", 10000.0)
        sub = Operation(code="Sous-traitance", label="Ogive", typology="Sous-traitance")
        sub.costs["Stueken"] = _subcontract("Stueken", unit_price=0.5, tooling=19400.0, included=500)
        if legacy:
            p = Project(name="P", reference="R", client="C", operations=[op, sub],
                        serie_data=SerieData(annual_volume=100000))
            p.switch_to_version(2)
        else:
            p = Project(name="P", reference="R", client="C", operations=[op, sub])
            v = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=100000)
            p.switch_to_version(v.version_index)
        p.operations  # pose le contexte de calcul de la version
        return p

    def test_new_decompose_version_syncs_purchases_tooling_and_setup(self):
        p = self._project_with_serie()
        sd = p.serie_data
        sd.sync_from_project(p)
        self.assertAlmostEqual(sd.synced_purchase_cost_per_piece, (100000 - 500) * 0.5 / 100000)
        self.assertAlmostEqual(sd.synced_setup_time_h, 2.0)
        self.assertEqual(sorted((t.name, t.cost) for t in sd.synced_tooling_items),
                         [("Découpe › Outil", 10000.0), ("Ogive › Outillage Stueken", 19400.0)])
        self.assertAlmostEqual(sd.tooling_cost_per_piece(), 29400.0 / 100000)
        self.assertAlmostEqual(sd.purchase_cost_per_piece(), sd.synced_purchase_cost_per_piece)

    def test_legacy_serie_data_is_not_altered_by_sync(self):
        p = self._project_with_serie(legacy=True)
        sd = p.serie_data
        before = (sd.selling_price_per_piece(), sd.tooling_cost_per_piece(), sd.setup_time_total_h())
        sd.sync_from_project(p)
        after = (sd.selling_price_per_piece(), sd.tooling_cost_per_piece(), sd.setup_time_total_h())
        # Seuls les postes machine (déjà synchronisés avant) évoluent
        self.assertEqual(before[1:], after[1:])
        self.assertEqual(sd.synced_tooling_items, [])

    def test_sync_restores_phase_context(self):
        p = self._project_with_serie()
        op = p.operations[0]
        ctx = op.phase_ctx
        p.serie_data.sync_from_project(p)
        self.assertEqual(op.phase_ctx, ctx)


class PhaseValidatorTest(unittest.TestCase):
    def _stueken_project(self):
        op = Operation(code="Sous-traitance", label="Ogive", typology="Sous-traitance")
        op.costs["Stueken"] = _subcontract("Stueken", unit_price=0.0, tooling=19400.0, included=500)
        return Project(name="P", reference="R", client="C", operations=[op], sale_quantities=[500, 600])

    def test_missing_price_beyond_included_pieces(self):
        from domain.quote_validator import QuoteValidator
        codes = [w.code for w in QuoteValidator.phase_warnings(self._stueken_project())]
        self.assertEqual(codes, ["PRICE_MISSING_BEYOND_INCLUDED"])

    def test_price_given_beyond_included_pieces_raises_no_warning(self):
        from domain.quote_validator import QuoteValidator
        p = self._stueken_project()
        p.operations[0].costs["Stueken"].pricing.unit_price = 30.0
        self.assertEqual(QuoteValidator.phase_warnings(p), [])


class SerieStepValuesTest(unittest.TestCase):
    def _project(self):
        op = Operation(code="Microdécoupe", label="Découpe", typology="Interne")
        c = _internal("Découpe Latérale", fixed_h=2.0, per_piece_h=120 / 3600, rate=120.0)
        op.costs[c.name] = c
        p = Project(name="P", reference="R", client="C", operations=[op], sale_quantities=[500])
        proto_price = p.total_price(500)
        v2 = p.add_version_variant("Décomposé", PhaseKind.SERIE, annual_volume=500000)
        v2.serie_data.global_commercial_margin = 0.0
        v2.serie_data.overhead_coef = 0.0
        p.switch_to_version(v2.version_index)
        c2 = p.operations[0].costs["Découpe Latérale"]
        return p, c2, v2.serie_data, proto_price

    def test_serie_values_inherit_from_the_copied_step(self):
        p, c, sd, _ = self._project()
        self.assertTrue(c.serie_is_inherited())
        self.assertAlmostEqual(c.serie_cycle_s(), 120.0)
        self.assertAlmostEqual(c.serie_rate(), 120.0)
        self.assertAlmostEqual(c.serie_setup(), 2.0)
        sd.sync_from_project(p)
        self.assertAlmostEqual(sd.machine_posts[0].cycle_time_s, 120.0)

    def test_serie_entry_overrides_without_touching_the_taux_horaire_version(self):
        p, c, sd, proto_price = self._project()
        c.serie_cycle_time_s = 36.0
        c.serie_pieces_per_cycle = 2.0
        c.serie_hourly_rate = 90.0
        sd.sync_from_project(p)
        self.assertAlmostEqual(sd.machine_posts[0].cycle_time_s, 18.0)
        self.assertAlmostEqual(sd.machine_posts[0].mo_rate_euro_per_h, 90.0)
        p.switch_to_version(1)
        self.assertAlmostEqual(p.total_price(500), proto_price)  # le Taux horaire ne bouge pas

    def test_trial_values_do_not_modify_data(self):
        p, c, sd, _ = self._project()
        sd.sync_from_project(p)
        base = sd.selling_price_per_piece()
        trial = sd.price_with_overrides(p, p.current_phase, {id(c): {"cycle_s": 60.0, "rate": 120.0}})
        # MO linéaire en TC × taux : moitié du temps → moitié du coût MO
        self.assertAlmostEqual(trial, base - (120 * 120 - 60 * 120) / 3600)
        self.assertAlmostEqual(sd.selling_price_per_piece(), base)
        self.assertIsNone(c.serie_cycle_time_s)

    def test_serie_values_roundtrip(self):
        p, c, sd, _ = self._project()
        c.serie_cycle_time_s, c.serie_hourly_rate = 36.0, 95.0
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.mwq")
            PersistenceService.save_project(p, path)
            q = PersistenceService.load_project(path)
        qc = q.versions[1].operations[0].costs["Découpe Latérale"]
        self.assertEqual((qc.serie_cycle_time_s, qc.serie_hourly_rate), (36.0, 95.0))
        self.assertIsNone(qc.serie_pieces_per_cycle)


if __name__ == "__main__":
    unittest.main()
