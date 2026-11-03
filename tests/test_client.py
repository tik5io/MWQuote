import json

from domain.client import (
    SECTOR_AERO, SECTOR_MEDICAL, SECTOR_OTHER, PROTOTYPE_LINES, traceability_mentions,
)
from domain.project import Project
from infrastructure.configuration import ConfigurationService
from infrastructure.export_service import ExportService


def test_mentions_medical():
    assert traceability_mentions(SECTOR_MEDICAL) == ["Traçabilité et suivi ISO 9100 Non applicable"]


def test_mentions_aero():
    assert traceability_mentions(SECTOR_AERO) == ["Traçabilité et suivi ISO 13485 Non applicable"]


def test_mentions_other_and_unknown():
    both = ["Traçabilité et suivi ISO 13485 Non applicable",
            "Traçabilité et suivi ISO 9100 Non applicable"]
    assert traceability_mentions(SECTOR_OTHER) == both
    assert traceability_mentions("") == both


def test_client_registry(tmp_path):
    cfg = ConfigurationService(config_path=str(tmp_path / "cfg.json"))
    cfg.add_client("Zeta", SECTOR_AERO)
    cfg.add_client("alpha", SECTOR_MEDICAL)
    cfg.add_client("ZETA", SECTOR_OTHER)  # même nom : mise à jour
    assert [c["name"] for c in cfg.get_clients()] == ["alpha", "ZETA"]
    assert cfg.get_client_sector("zeta") == SECTOR_OTHER
    assert cfg.get_client_sector("inconnu") is None
    assert json.loads((tmp_path / "cfg.json").read_text(encoding="utf-8"))["clients"]


def test_global_comment_sector_inherited_from_client_registry(monkeypatch, tmp_path):
    cfg = ConfigurationService(config_path=str(tmp_path / "cfg.json"))
    cfg.add_client("C", SECTOR_AERO)
    monkeypatch.setattr(ConfigurationService, "get_instance", classmethod(lambda cls: cfg))
    # la copie du projet (Médical) est périmée : la base clients (Aéronautique) fait foi
    project = Project(name="p", reference="R", client="C", client_sector=SECTOR_MEDICAL)
    text = ExportService()._build_global_comment(project)
    assert "ISO 13485 Non applicable" in text
    assert "ISO 9100 Non applicable" not in text


def test_global_comment_includes_mentions_and_prototype():
    project = Project(name="p", reference="R", client="C", client_sector=SECTOR_MEDICAL, is_prototype=True)
    text = ExportService()._build_global_comment(project)
    assert "ISO 9100 Non applicable" in text
    assert "ISO 13485 Non applicable" not in text
    for line in PROTOTYPE_LINES:
        assert line in text


def _roundtrip(project, tmp_path, mutate=None):
    import json, zipfile
    from infrastructure.persistence import PersistenceService
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
