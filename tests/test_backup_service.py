"""Sauvegarde hebdomadaire : contenu du zip, échéance, ménage."""
import datetime
import os
import sqlite3
import zipfile

import pytest

from infrastructure.backup_service import BackupService, CONFIG_ARCDIR


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "mwquote_index.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE quote_numbers (date TEXT, counter INTEGER)")
    conn.execute("INSERT INTO quote_numbers VALUES ('2026-07-20', 1)")
    conn.commit()
    conn.close()
    projects = tmp_path / "MWQUOTE-DATA"
    (projects / "sub").mkdir(parents=True)
    (projects / "a.mwq").write_bytes(b"PKaaa")
    (projects / "sub" / "b.mwq").write_bytes(b"PKbbb")
    (projects / "notes.txt").write_text("pas un projet")
    cfg = tmp_path / "app_config.json"
    cfg.write_text('{"clients": []}')
    svc = BackupService(str(db), str(projects), str(cfg), str(tmp_path / "bk"), keep=3)
    return svc, tmp_path


def test_backup_contains_db_projects_and_config(env):
    svc, _ = env
    path = svc.create_backup(datetime.datetime(2026, 11, 5, 9, 0, 0))
    assert os.path.basename(path) == "mwquote-backup-20261105-090000.zip"
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        assert "mwquote_index.db" in names
        assert f"{CONFIG_ARCDIR}/app_config.json" in names
        assert "MANIFEST.json" in names
        assert {"MWQUOTE-DATA/a.mwq", "MWQUOTE-DATA\\sub\\b.mwq"} & names
        assert not any(n.endswith("notes.txt") for n in names)
        zf.extract("mwquote_index.db", svc.backup_dir)
    restored = sqlite3.connect(os.path.join(svc.backup_dir, "mwquote_index.db"))
    assert restored.execute("SELECT counter FROM quote_numbers").fetchone() == (1,)   # compteur d'offres sauvé
    restored.close()
    assert not [f for f in os.listdir(svc.backup_dir) if f.endswith(".part")]


def test_is_due_after_a_week(env):
    svc, _ = env
    t0 = datetime.datetime(2026, 11, 5, 9, 0, 0)
    assert svc.is_due(t0)                                   # aucune sauvegarde
    svc.create_backup(t0)
    assert not svc.is_due(t0 + datetime.timedelta(days=6, hours=23))
    assert svc.is_due(t0 + datetime.timedelta(days=7))


def test_run_if_due_prunes_to_keep(env):
    svc, _ = env
    t = datetime.datetime(2026, 1, 1, 8, 0, 0)
    for week in range(5):
        assert svc.run_if_due(t + datetime.timedelta(weeks=week)) is not None
    stamps = [s for s, _ in svc.list_backups()]
    assert len(stamps) == 3                                  # keep=3
    assert stamps[-1] == t + datetime.timedelta(weeks=4)     # on garde les plus récentes
    assert svc.run_if_due(t + datetime.timedelta(weeks=4, days=1)) is None


def test_missing_sources_do_not_crash(tmp_path):
    svc = BackupService(str(tmp_path / "none.db"), str(tmp_path / "nodir"),
                        str(tmp_path / "nocfg.json"), str(tmp_path / "bk"))
    path = svc.create_backup()
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist() == ["MANIFEST.json"]
