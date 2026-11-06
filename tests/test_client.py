import json
import zipfile

import pytest

from domain.client import (
    SECTOR_AERO, SECTOR_MEDICAL, SECTORS, PROTOTYPE_LINES, normalize_sectors, traceability_mentions,
)
from domain.project import Project
from infrastructure.configuration import ConfigurationService
from infrastructure.export_service import ExportService
from infrastructure.persistence import PersistenceService

NA_13485 = "Traçabilité et suivi ISO 13485 Non applicable"
NA_9100 = "Traçabilité et suivi ISO 9100 Non applicable"


# --------------------------------------------------------------------------- domaines (au niveau projet)

def test_mentions_medical():
    assert traceability_mentions([SECTOR_MEDICAL]) == [NA_9100]


def test_mentions_aero():
    assert traceability_mentions([SECTOR_AERO]) == [NA_13485]


def test_mentions_both_sectors_have_no_non_applicable_mention():
    assert traceability_mentions([SECTOR_MEDICAL, SECTOR_AERO]) == []


def test_mentions_no_sector_means_both_non_applicable():
    assert traceability_mentions([]) == [NA_13485, NA_9100]
    assert traceability_mentions(None) == [NA_13485, NA_9100]
    assert traceability_mentions("") == [NA_13485, NA_9100]


def test_normalize_sectors_accepts_legacy_single_string():
    assert normalize_sectors("Médical") == [SECTOR_MEDICAL]
    assert normalize_sectors("Autre") == []                     # ancien « Autre » : aucun domaine
    assert normalize_sectors(["Aéronautique", "Médical", "Médical", "x"]) == SECTORS   # ordre fixe, sans doublon


def test_project_sectors_default_and_legacy_argument():
    assert Project(name="p", reference="R", client="C").sectors == []
    assert Project(name="p", reference="R", client="C", client_sector="Aéronautique").sectors == [SECTOR_AERO]
    assert Project(name="p", reference="R", client="C", sectors=SECTORS).sectors == SECTORS


def test_split_version_keeps_sectors():
    p = Project(name="p", reference="R", client="C", sectors=[SECTOR_MEDICAL])
    assert p.split_version_to_project(1).sectors == [SECTOR_MEDICAL]


# --------------------------------------------------------------------------- client = nom seul

def test_client_registry_is_names_only(tmp_path):
    cfg = ConfigurationService(config_path=str(tmp_path / "cfg.json"))
    cfg.add_client("Zeta")
    cfg.add_client("alpha")
    cfg.add_client("ZETA")                                      # même nom (casse ignorée) : remplace
    assert cfg.get_clients() == [{"name": "alpha"}, {"name": "ZETA"}]
    assert cfg.has_client("zeta") and not cfg.has_client("inconnu")
    cfg.update_client("alpha", "Beta")
    assert [c["name"] for c in cfg.get_clients()] == ["Beta", "ZETA"]
    cfg.remove_client("beta")
    assert [c["name"] for c in cfg.get_clients()] == ["ZETA"]
    assert json.loads((tmp_path / "cfg.json").read_text(encoding="utf-8"))["clients"] == [{"name": "ZETA"}]


def test_config_migration_strips_client_sector_but_keeps_it_for_old_projects(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"clients": [{"name": "Abbott", "sector": "Médical"},
                                            {"name": "Eupry", "sector": "Autre"}]}), encoding="utf-8")
    cfg = ConfigurationService(config_path=str(path))
    assert cfg.get_clients() == [{"name": "Abbott"}, {"name": "Eupry"}]          # plus que le nom
    assert "sector" not in json.dumps(cfg.config["clients"])
    assert cfg.get_legacy_client_sector("ABBOTT") == "Médical"                    # pour migrer les anciens fichiers
    assert json.loads(path.read_text(encoding="utf-8"))["clients"] == [{"name": "Abbott"}, {"name": "Eupry"}]
    assert ConfigurationService(config_path=str(path)).get_legacy_client_sector("abbott") == "Médical"   # idempotent


# --------------------------------------------------------------------------- mentions dans l'offre

def test_global_comment_uses_project_sectors():
    both = Project(name="p", reference="R", client="C", sectors=SECTORS)
    text = ExportService()._build_global_comment(both)
    assert "Non applicable" not in text

    none = Project(name="p", reference="R", client="C")
    text = ExportService()._build_global_comment(none)
    assert NA_13485 in text and NA_9100 in text


def test_global_comment_includes_mentions_and_prototype():
    project = Project(name="p", reference="R", client="C", sectors=[SECTOR_MEDICAL], is_prototype=True)
    text = ExportService()._build_global_comment(project)
    assert NA_9100 in text and NA_13485 not in text
    for line in PROTOTYPE_LINES:
        assert line in text


# --------------------------------------------------------------------------- persistance et migration

def _roundtrip(project, tmp_path, mutate=None):
    path = str(tmp_path / "p.mwq")
    PersistenceService.save_project(project, path)
    if mutate:
        with zipfile.ZipFile(path) as zin:
            items = [(i, zin.read(i.filename)) for i in zin.infolist()]
        with zipfile.ZipFile(path, "w") as zout:
            for i, data in items:
                if i.filename == "project.json":
                    data = json.dumps(mutate(json.loads(data))).encode("utf-8")
                zout.writestr(i, data)
    return PersistenceService.load_project(path)


def test_sectors_survive_save_and_load(tmp_path):
    p = Project(name="p", reference="R", client="C", sectors=SECTORS)
    q = _roundtrip(p, tmp_path)
    assert q.sectors == SECTORS


def test_no_sector_survives_save_and_load(tmp_path):
    q = _roundtrip(Project(name="p", reference="R", client="C"), tmp_path)
    assert q.sectors == []


def _legacy(client_sector):
    def mutate(d):
        d.pop("sectors", None)
        d["client_sector"] = client_sector
        return d
    return mutate


def test_legacy_file_client_sector_is_converted(tmp_path, monkeypatch):
    cfg = ConfigurationService(config_path=str(tmp_path / "cfg.json"))         # aucun secteur hérité
    monkeypatch.setattr(ConfigurationService, "get_instance", classmethod(lambda cls: cfg))
    p = Project(name="p", reference="R", client="C")
    assert _roundtrip(p, tmp_path, _legacy("Aéronautique")).sectors == [SECTOR_AERO]
    assert _roundtrip(p, tmp_path, _legacy("Autre")).sectors == []
    assert _roundtrip(p, tmp_path, _legacy("")).sectors == []


def test_legacy_file_client_registry_sector_wins_as_before(tmp_path, monkeypatch):
    """Avant, la base clients faisait foi sur la copie du projet : les mentions des offres ne changent pas."""
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"clients": [{"name": "C", "sector": "Aéronautique"}]}), encoding="utf-8")
    cfg = ConfigurationService(config_path=str(path))
    monkeypatch.setattr(ConfigurationService, "get_instance", classmethod(lambda cls: cfg))
    p = Project(name="p", reference="R", client="C")
    q = _roundtrip(p, tmp_path, _legacy("Médical"))             # la copie du projet (Médical) est périmée
    assert q.sectors == [SECTOR_AERO]
    text = ExportService()._build_global_comment(q)
    assert NA_13485 in text and NA_9100 not in text


def test_current_format_ignores_legacy_registry(tmp_path, monkeypatch):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"clients": [{"name": "C", "sector": "Médical"}]}), encoding="utf-8")
    cfg = ConfigurationService(config_path=str(path))
    monkeypatch.setattr(ConfigurationService, "get_instance", classmethod(lambda cls: cfg))
    p = Project(name="p", reference="R", client="C", sectors=[])             # décoché volontairement
    assert _roundtrip(p, tmp_path).sectors == []


# --------------------------------------------------------------------------- prototype : au niveau du scénario

def test_prototype_is_per_version(tmp_path):
    p = Project(name="p", reference="R", client="C")
    v2 = p.add_version("v2")
    p.is_prototype = True                      # version courante (V1)
    assert p.get_version(1).is_prototype and not v2.is_prototype
    p.switch_to_version(2)
    assert p.is_prototype is False
    q = _roundtrip(p, tmp_path)
    assert [v.is_prototype for v in q.versions] == [True, False]


def test_prototype_legacy_project_level_flag_applies_to_all_versions(tmp_path):
    p = Project(name="p", reference="R", client="C")
    p.add_version("v2")

    def legacy(d):
        d["is_prototype"] = True
        for v in d["versions"]:
            v.pop("is_prototype", None)
        return d

    q = _roundtrip(p, tmp_path, legacy)
    assert all(v.is_prototype for v in q.versions)


def test_prototype_mentions_follow_the_scenario_being_offered():
    p = Project(name="p", reference="R", client="C", sectors=SECTORS)
    p.add_version("série")
    p.get_version(1).is_prototype = True
    p.switch_to_version(1)
    assert all(line in ExportService()._build_global_comment(p) for line in PROTOTYPE_LINES)
    p.switch_to_version(2)
    assert not any(line in ExportService()._build_global_comment(p) for line in PROTOTYPE_LINES)


def test_phase_dialog_prototype_checkbox():
    import wx
    from ui.dialogs.phase_dialog import PhaseDialog
    app = wx.App(False)                                           # noqa: F841
    dlg = PhaseDialog(None, prototype=True)
    try:
        assert dlg.get_prototype() is True
        dlg.prototype_chk.SetValue(False)
        assert dlg.get_prototype() is False
    finally:
        dlg.Destroy()
    dlg = PhaseDialog(None)
    try:
        assert dlg.get_prototype() is False                       # par défaut : pas prototype
    finally:
        dlg.Destroy()
