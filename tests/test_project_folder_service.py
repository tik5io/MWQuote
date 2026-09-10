# tests/test_project_folder_service.py
"""
Tests pour le service de gestion du dossier physique d'un projet série.
"""

import os
import base64
import shutil
import tempfile
import unittest

from infrastructure.configuration import ConfigurationService
from infrastructure.project_folder_service import (
    ProjectFolderService,
    sanitize_folder_name,
    PLANS_SUBPATH,
    COMMERCIAL_SUBPATH,
    SUPPLIER_QUOTES_SUBPATH,
    PROCESS_SUBPATH,
)
from domain.project import Project
from domain.document import Document
from domain.operation import Operation
from domain.cost import CostItem, CostType, PricingStructure, PricingType
from infrastructure.persistence import PersistenceService


class _FakeConfig:
    """Config minimale isolée du fichier AppData réel."""

    def __init__(self, root, empty_name="0 - EMPTY PROJECT"):
        self._root = root
        self._empty = empty_name

    def get_series_root_folder(self):
        return self._root

    def get_empty_project_name(self):
        return self._empty


class TestProjectFolderService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "0 - PROJET SERIE")
        os.makedirs(self.root, exist_ok=True)
        self.config = _FakeConfig(self.root)
        self.service = ProjectFolderService(config=self.config)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build_template(self):
        """Crée un dossier modèle 0 - EMPTY PROJECT avec l'arborescence type."""
        template = os.path.join(self.root, "0 - EMPTY PROJECT")
        os.makedirs(os.path.join(template, PLANS_SUBPATH), exist_ok=True)
        os.makedirs(os.path.join(template, COMMERCIAL_SUBPATH), exist_ok=True)
        # Un fichier modèle à copier
        with open(os.path.join(template, COMMERCIAL_SUBPATH, "modele.txt"), "w") as f:
            f.write("modele")
        return template

    # ------------------------------------------------------------------ #

    def test_sanitize_folder_name(self):
        self.assertEqual(sanitize_folder_name("ACME/Corp"), "ACMECorp")
        self.assertEqual(sanitize_folder_name("  Projet X.  "), "Projet X")
        self.assertEqual(sanitize_folder_name(""), "")

    def test_suggest_folder(self):
        path = self.service.suggest_folder("ACME", "PRJ-001")
        self.assertEqual(path, os.path.join(self.root, "ACME", "PRJ-001"))

    def test_suggest_folder_empty(self):
        self.assertEqual(self.service.suggest_folder("", ""), "")

    def test_suggest_folder_partial(self):
        self.assertEqual(
            self.service.suggest_folder("ACME", ""), os.path.join(self.root, "ACME")
        )

    def test_subpaths(self):
        folder = os.path.join(self.root, "ACME", "PRJ")
        self.assertEqual(self.service.plans_dir(folder), os.path.join(folder, PLANS_SUBPATH))
        self.assertEqual(
            self.service.commercial_dir(folder), os.path.join(folder, COMMERCIAL_SUBPATH)
        )
        self.assertEqual(
            self.service.supplier_quotes_dir(folder),
            os.path.join(folder, SUPPLIER_QUOTES_SUBPATH),
        )
        self.assertEqual(
            self.service.process_dir(folder), os.path.join(folder, PROCESS_SUBPATH)
        )

    def test_create_folder_tree_from_template(self):
        self._build_template()
        dest = os.path.join(self.root, "ACME", "PRJ")
        stats = self.service.create_folder_tree(dest)
        self.assertTrue(os.path.isdir(os.path.join(dest, PLANS_SUBPATH)))
        self.assertTrue(os.path.isdir(os.path.join(dest, COMMERCIAL_SUBPATH)))
        self.assertTrue(os.path.isfile(os.path.join(dest, COMMERCIAL_SUBPATH, "modele.txt")))
        self.assertEqual(stats["copied_files"], 1)

    def test_create_folder_tree_without_template(self):
        # Pas de dossier modèle → arborescence standard minimale
        dest = os.path.join(self.root, "ACME", "PRJ")
        self.service.create_folder_tree(dest)
        self.assertTrue(os.path.isdir(os.path.join(dest, PLANS_SUBPATH)))
        self.assertTrue(os.path.isdir(os.path.join(dest, COMMERCIAL_SUBPATH)))

    def test_create_folder_tree_no_overwrite(self):
        self._build_template()
        dest = os.path.join(self.root, "ACME", "PRJ")
        os.makedirs(os.path.join(dest, COMMERCIAL_SUBPATH), exist_ok=True)
        existing = os.path.join(dest, COMMERCIAL_SUBPATH, "modele.txt")
        with open(existing, "w") as f:
            f.write("ORIGINAL")
        # decider par défaut (None) → ne pas écraser
        stats = self.service.create_folder_tree(dest)
        with open(existing) as f:
            self.assertEqual(f.read(), "ORIGINAL")
        self.assertEqual(stats["skipped_files"], 1)

    def test_create_folder_tree_overwrite(self):
        self._build_template()
        dest = os.path.join(self.root, "ACME", "PRJ")
        os.makedirs(os.path.join(dest, COMMERCIAL_SUBPATH), exist_ok=True)
        existing = os.path.join(dest, COMMERCIAL_SUBPATH, "modele.txt")
        with open(existing, "w") as f:
            f.write("ORIGINAL")
        stats = self.service.create_folder_tree(dest, overwrite_decider=lambda rel: True)
        with open(existing) as f:
            self.assertEqual(f.read(), "modele")
        self.assertEqual(stats["copied_files"], 1)

    def test_copy_project_plans(self):
        dest = os.path.join(self.root, "ACME", "PRJ")
        data = base64.b64encode(b"%PDF-1.4 fake").decode("ascii")
        project = Project(
            name="p", reference="PRJ", client="ACME",
            documents=[Document(filename="abc.pdf", data=data)],
        )
        stats = self.service.copy_project_plans(project, dest)
        self.assertEqual(stats["copied_files"], 1)
        self.assertTrue(os.path.isfile(os.path.join(dest, PLANS_SUBPATH, "abc.pdf")))

    def test_copy_latest_devis_xlsx(self):
        dest = os.path.join(self.root, "ACME", "PRJ")
        project = Project(name="p", reference="PRJ", client="ACME")
        project.export_history = [
            {"devis_ref": "D1", "date": "2026-01-01"},  # sans binaire
            {"devis_ref": "D2", "date": "2026-02-01",
             "xlsx_filename": "D2.xlsx",
             "xlsx_data_b64": base64.b64encode(b"xlsx-late").decode("ascii")},
        ]
        stats = self.service.copy_latest_devis_xlsx(project, dest)
        self.assertEqual(stats["copied_files"], 1)
        out = os.path.join(dest, COMMERCIAL_SUBPATH, "D2.xlsx")
        self.assertTrue(os.path.isfile(out))
        with open(out, "rb") as f:
            self.assertEqual(f.read(), b"xlsx-late")

    def test_copy_latest_devis_xlsx_none(self):
        dest = os.path.join(self.root, "ACME", "PRJ")
        project = Project(name="p", reference="PRJ", client="ACME")
        stats = self.service.copy_latest_devis_xlsx(project, dest)
        self.assertEqual(stats["copied_files"], 0)

    def _project_with_supplier_docs(self):
        data = base64.b64encode(b"quote").decode("ascii")
        cost = CostItem(
            name="Sous-trait", cost_type=CostType.SUBCONTRACTING,
            pricing=PricingStructure(pricing_type=PricingType.PER_UNIT),
            documents=[Document(filename="devis_fournA.pdf", data=data)],
            supplier_quote_ref="F-001",
        )
        op = Operation(code="10", label="Op", costs={"Sous-trait": cost})
        return Project(name="p", reference="PRJ", client="ACME", operations=[op])

    def test_copy_supplier_quotes(self):
        dest = os.path.join(self.root, "ACME", "PRJ")
        project = self._project_with_supplier_docs()
        stats = self.service.copy_supplier_quotes(project, dest)
        self.assertEqual(stats["copied_files"], 1)
        self.assertTrue(
            os.path.isfile(os.path.join(dest, SUPPLIER_QUOTES_SUBPATH, "devis_fournA.pdf"))
        )

    def test_copy_supplier_quotes_dedupe(self):
        dest = os.path.join(self.root, "ACME", "PRJ")
        data = base64.b64encode(b"q").decode("ascii")
        cost1 = CostItem(name="c1", cost_type=CostType.SUBCONTRACTING,
                         pricing=PricingStructure(pricing_type=PricingType.PER_UNIT),
                         documents=[Document(filename="devis.pdf", data=data)])
        cost2 = CostItem(name="c2", cost_type=CostType.MATERIAL,
                         pricing=PricingStructure(pricing_type=PricingType.PER_UNIT),
                         documents=[Document(filename="devis.pdf", data=data)])
        op = Operation(code="10", label="Op", costs={"c1": cost1, "c2": cost2})
        project = Project(name="p", reference="PRJ", client="ACME", operations=[op])
        stats = self.service.copy_supplier_quotes(project, dest)
        self.assertEqual(stats["copied_files"], 2)
        d = os.path.join(dest, SUPPLIER_QUOTES_SUBPATH)
        self.assertTrue(os.path.isfile(os.path.join(d, "devis.pdf")))
        self.assertTrue(os.path.isfile(os.path.join(d, "devis_2.pdf")))

    def test_copy_supplier_quotes_none(self):
        dest = os.path.join(self.root, "ACME", "PRJ")
        project = Project(name="p", reference="PRJ", client="ACME")
        stats = self.service.copy_supplier_quotes(project, dest)
        self.assertEqual(stats["copied_files"], 0)
        self.assertFalse(os.path.isdir(os.path.join(dest, SUPPLIER_QUOTES_SUBPATH)))

    def test_copy_project_plans_strips_uuid_prefix(self):
        dest = os.path.join(self.root, "ACME", "PRJ")
        uuid_name = "550e8400-e29b-41d4-a716-446655440000_plan.pdf"
        data = base64.b64encode(b"x").decode("ascii")
        project = Project(
            name="p", reference="PRJ", client="ACME",
            documents=[Document(filename=uuid_name, data=data)],
        )
        self.service.copy_project_plans(project, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, PLANS_SUBPATH, "plan.pdf")))


class TestFabricationExportToProcess(unittest.TestCase):
    """L'export Fabrication/Qualité écrit un XLSX valide dans <projet>\\PROCESS."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_fabrication_into_process_dir(self):
        from infrastructure.export_service import ExportService
        from infrastructure.project_folder_service import ProjectFolderService as PFS

        project_folder = os.path.join(self.tmp, "ACME", "PRJ")
        process_dir = PFS.process_dir(project_folder)
        os.makedirs(process_dir, exist_ok=True)

        cost = CostItem(
            name="Op interne", cost_type=CostType.INTERNAL_OPERATION,
            pricing=PricingStructure(pricing_type=PricingType.PER_UNIT),
            per_piece_time=0.5, hourly_rate=40.0,
        )
        op = Operation(code="10", label="Tournage", typology="USINAGE",
                       costs={"Op interne": cost})
        project = Project(name="p", reference="PRJ-001", client="ACME",
                          project_folder=project_folder, operations=[op])

        output_path = os.path.join(process_dir, "PRJ-001_Fabrication_Qualite.xlsx")
        result = ExportService().export_fabrication_quality(project, output_path)
        self.assertTrue(result)
        self.assertTrue(os.path.isfile(output_path))
        # Le fichier doit être un xlsx (ZIP) non vide
        self.assertGreater(os.path.getsize(output_path), 0)


class TestProjectFolderPersistence(unittest.TestCase):
    """Le champ project_folder doit survivre à un aller-retour .mwq."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        folder = r"Z:\0 - PROJET SERIE\ACME\PRJ-001"
        project = Project(name="p", reference="PRJ-001", client="ACME", project_folder=folder)
        path = os.path.join(self.tmp, "test.mwq")
        PersistenceService.save_project(project, path)
        loaded = PersistenceService.load_project(path)
        self.assertEqual(loaded.project_folder, folder)

    def test_default_empty(self):
        project = Project(name="p", reference="R", client="C")
        self.assertEqual(project.project_folder, "")


class TestConfigurationSeriesRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.tmp, "app_config.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_series_root(self):
        cfg = ConfigurationService(config_path=self.cfg_path)
        self.assertEqual(cfg.get_series_root_folder(), ConfigurationService.DEFAULT_SERIES_ROOT)
        self.assertEqual(cfg.get_empty_project_name(), ConfigurationService.DEFAULT_EMPTY_PROJECT_NAME)

    def test_set_series_root_persists(self):
        cfg = ConfigurationService(config_path=self.cfg_path)
        cfg.set_series_root_folder(r"D:\autre")
        cfg2 = ConfigurationService(config_path=self.cfg_path)
        self.assertEqual(cfg2.get_series_root_folder(), r"D:\autre")


if __name__ == "__main__":
    unittest.main()
