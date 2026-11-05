"""Dupliquer / supprimer une version, et lien avec les offres qui la figent."""
import pytest

from domain import offers
from domain.project import Project


def _project_with_versions(n=3):
    p = Project(name="P", reference="R", client="C")
    for _ in range(n - 1):
        p.add_version("")
    return p


def _issue(project, version_index, ref, revisions=("A",)):
    for rev in revisions:
        project.export_history.append(
            {"devis_ref": ref, "version_index": version_index, "revision": rev, "xlsx_data_b64": "AAAA"})


def test_duplicate_version_is_a_free_copy():
    p = _project_with_versions(2)
    p.current_version.label = "Proto"
    _issue(p, 1, "OD260720_001")
    assert p.is_version_frozen(1)

    copy_v = p.duplicate_version(1)

    assert copy_v.version_index == 3
    assert copy_v.label == "V1 (copie)" or copy_v.label.endswith("(copie)")
    assert copy_v.created_from_version == 1
    assert not p.is_version_frozen(copy_v.version_index)   # la copie n'est jamais figée
    assert p.is_version_frozen(1)                          # l'original l'est toujours
    assert copy_v is not p.get_version(1)
    assert copy_v.phase is not p.get_version(1).phase      # copie profonde


def test_duplicate_version_uses_label_of_source():
    p = _project_with_versions(1)
    p.current_version.label = "Série"
    assert p.duplicate_version().label == "Série (copie)"


def test_version_offers_lists_offers_of_the_version_only():
    p = _project_with_versions(3)
    _issue(p, 2, "OD260720_001", revisions=("A", "B"))
    _issue(p, 3, "OD260721_002")
    assert offers.version_offers(p.export_history, 2) == [("OD260720_001", 2)]
    assert offers.version_offers(p.export_history, 1) == []


def test_delete_version_removes_its_offers_and_keeps_others():
    p = _project_with_versions(3)
    _issue(p, 2, "OD260720_001")
    _issue(p, 3, "OD260721_002")

    assert p.delete_version(2) is True

    assert [v.version_index for v in p.versions] == [1, 3]
    assert [e["devis_ref"] for e in p.export_history] == ["OD260721_002"]
    assert not p.is_version_frozen(2)


def test_deleted_index_reused_is_not_falsely_frozen():
    p = _project_with_versions(2)
    _issue(p, 2, "OD260720_001")
    p.delete_version(2)
    new_v = p.add_version("")
    assert new_v.version_index == 2
    assert not p.is_version_frozen(2)


def test_delete_current_version_switches_to_previous():
    p = _project_with_versions(3)
    p.switch_to_version(3)
    p.delete_version(3)
    assert p.current_version_index == 2

    p.switch_to_version(1)
    p.delete_version(1)
    assert p.current_version_index == 2   # plus de précédente : la première restante


def test_cannot_delete_last_or_unknown_version():
    p = _project_with_versions(1)
    assert p.delete_version(1) is False
    assert p.delete_version(99) is False
    assert len(p.versions) == 1
