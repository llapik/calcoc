"""End-to-end tests for the repair pipeline: safety → backup → action → journal → rollback."""

import os
import time
from pathlib import Path

import pytest

from src.core.app import create_app
from src.core.config import Config
from src.repair import executor as ex_mod
from src.repair.executor import RepairExecutor, _stale_files
from src.rollback.backup import BackupManager
from src.rollback.journal import Journal


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("AI_BACKEND", "none")
    return Config()


@pytest.fixture
def client(config):
    return create_app(config).test_client()


def _load(client, scenario):
    assert client.post("/api/demo", json={"scenario": scenario}).status_code == 200
    assert client.post("/api/scan").get_json()["status"] == "ok"
    return client.post("/api/problems").get_json()["problems"]


def _by_action(problems, action):
    return next(p for p in problems if p["fix_action"] == action and p["status"] == "open")


class TestDemoPipeline:
    def test_every_scenario_scans_and_analyses(self, client):
        scenarios = client.get("/api/demo").get_json()["scenarios"]
        assert len(scenarios) >= 5
        for s in scenarios:
            _load(client, s["id"])
        assert _load(client, "healthy") == []

    def test_problems_require_scan(self, client):
        assert client.post("/api/problems").status_code == 400

    def test_cleanup_needs_confirmation_then_moves_files_and_rolls_back(self, client, config):
        problems = _load(client, "dying_hdd")
        problem = _by_action(problems, "clean_temp_files")
        assert problem["fix"]["risk_level"] == "yellow"
        junk = config.data_dir / "demo_sandbox" / "dying_hdd" / "junk"
        before = sorted(p for p in junk.rglob("*") if p.is_file())
        assert before

        # Unconfirmed: nothing happens
        out = client.post("/api/repair", json={"problem_id": problem["id"]}).get_json()["outcome"]
        assert out["status"] == "needs_confirmation"
        assert sorted(p for p in junk.rglob("*") if p.is_file()) == before

        out = client.post("/api/repair", json={"problem_id": problem["id"], "confirm": True}).get_json()["outcome"]
        assert out["status"] == "done" and out["can_rollback"] and out["simulated"]
        assert out["details"]["files"] == len(before)
        assert not [p for p in junk.rglob("*") if p.is_file()]

        # Problem is reported as fixed and the scenario reflects the freed space
        problems = client.post("/api/problems").get_json()["problems"]
        fixed = [p for p in problems if p["status"] == "fixed"]
        assert [p["journal_id"] for p in fixed] == [out["journal_id"]]
        assert not [p for p in problems if p["fix_action"] == "clean_temp_files" and p["status"] == "open"]

        journal = client.get("/api/journal").get_json()["entries"]
        assert journal[0]["id"] == out["journal_id"] and journal[0]["can_rollback"]

        # Rollback puts every file back and reopens the problem
        assert client.post(f"/api/journal/{out['journal_id']}/rollback").status_code == 200
        assert sorted(p for p in junk.rglob("*") if p.is_file()) == before
        problems = client.post("/api/problems").get_json()["problems"]
        assert _by_action(problems, "clean_temp_files")
        assert client.post(f"/api/journal/{out['journal_id']}/rollback").status_code == 409

    def test_malware_is_quarantined(self, client, config):
        problems = _load(client, "infected_office")
        trojan = next(p for p in problems if "Trojan" in p["title"] or "троян" in p["title"])
        sandbox = config.data_dir / "demo_sandbox" / "infected_office" / "infected"
        assert len([p for p in sandbox.rglob("*") if p.is_file()]) == 3

        out = client.post("/api/repair", json={"problem_id": trojan["id"], "confirm": True}).get_json()["outcome"]
        assert out["status"] == "done" and out["details"]["files"] == 2
        assert len([p for p in sandbox.rglob("*") if p.is_file()]) == 1

    def test_red_action_blocked_until_expert_mode(self, client, config):
        problems = _load(client, "broken_boot")
        boot = _by_action(problems, "fix_bootloader")
        assert boot["fix"]["availability"] == "blocked"
        out = client.post("/api/repair", json={"problem_id": boot["id"], "confirm": True}).get_json()["outcome"]
        assert out["status"] == "blocked" and out["journal_id"] is None

        client.post("/api/settings", json={"expert_mode": True})
        problems = client.post("/api/problems").get_json()["problems"]
        boot = _by_action(problems, "fix_bootloader")
        out = client.post("/api/repair", json={"problem_id": boot["id"], "confirm": True}).get_json()["outcome"]
        assert out["status"] == "done" and out["simulated"] and out["can_rollback"]

    def test_fixing_filesystem_reveals_windows(self, client):
        problems = _load(client, "broken_boot")
        fs = _by_action(problems, "fix_filesystem")
        client.post("/api/repair", json={"problem_id": fs["id"], "confirm": True})
        data = client.post("/api/scan").get_json()["data"]
        assert data["os"]["detected"][0]["name"] == "Windows"

    def test_unknown_problem_and_unfixable(self, client):
        problems = _load(client, "overheating_laptop")
        assert client.post("/api/repair", json={"problem_id": "P999"}).status_code == 404
        assert client.post("/api/repair", json={"problem_id": problems[0]["id"]}).status_code == 400

    def test_purge_releases_backups(self, client, config):
        problems = _load(client, "dying_hdd")
        problem = _by_action(problems, "clean_temp_files")
        out = client.post("/api/repair", json={"problem_id": problem["id"], "confirm": True}).get_json()["outcome"]
        assert client.post("/api/backups/purge").status_code == 200
        entry = next(e for e in client.get("/api/journal").get_json()["entries"] if e["id"] == out["journal_id"])
        assert entry["status"] == "purged" and not entry["can_rollback"]
        assert not any(config.path("backup_dir").iterdir())

    def test_leaving_demo_restores_real_mode(self, client):
        _load(client, "dying_hdd")
        client.post("/api/demo", json={"scenario": None})
        status = client.get("/api/status").get_json()
        assert status["demo"] is None and status["has_scan"] is False

    def test_unknown_scenario(self, client):
        assert client.post("/api/demo", json={"scenario": "../../etc/passwd"}).status_code == 404


class TestExecutorOutsideDemo:
    @pytest.fixture
    def executor(self, config):
        journal = Journal(config.file_path("journal_db"))
        return RepairExecutor(config, journal, BackupManager(config.path("backup_dir"), journal))

    def test_offline_repairs_unavailable_on_running_system(self, executor):
        out = executor.execute("fix_filesystem", confirmed=True)
        assert out.status == "unavailable" and out.journal_id is None

    def test_black_action_blocked(self, executor):
        assert executor.execute("flash_bios", confirmed=True).status == "blocked"
        assert executor.plan("flash_bios").status == "blocked"

    def test_desktop_cleanup_only_touches_old_files(self, executor, tmp_path, monkeypatch):
        temp = tmp_path / "temp"
        temp.mkdir()
        old, fresh = temp / "old.tmp", temp / "fresh.tmp"
        old.write_text("x" * 100)
        fresh.write_text("y")
        two_days_ago = time.time() - 48 * 3600
        os.utime(old, (two_days_ago, two_days_ago))
        monkeypatch.setattr(ex_mod, "_desktop_temp_dirs", lambda: [str(temp)])

        out = executor.execute("clean_temp_files", confirmed=True)
        assert out.status == "done" and out.details["files"] == 1
        assert not old.exists() and fresh.exists()

        assert executor.rollback(out.journal_id)
        assert old.read_text() == "x" * 100

    def test_cleanup_with_nothing_to_do_leaves_no_journal_entry(self, executor, tmp_path, monkeypatch):
        monkeypatch.setattr(ex_mod, "_desktop_temp_dirs", lambda: [str(tmp_path / "missing")])
        out = executor.execute("clean_temp_files", confirmed=True)
        assert out.status == "done" and out.journal_id is None
        assert executor.journal.get_recent() == []

    def test_stale_files_skips_excluded_dirs_and_symlinks(self, tmp_path):
        (tmp_path / "keep").mkdir()
        (tmp_path / "keep" / "a").write_text("a")
        (tmp_path / "b").write_text("b")
        (tmp_path / "link").symlink_to(tmp_path / "b")
        found = _stale_files([str(tmp_path)], 0, exclude=[str(tmp_path / "keep")])
        assert found == [str(tmp_path / "b")]


class TestRequestGuard:
    def test_foreign_host_rejected(self, client):
        assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 403

    def test_foreign_origin_rejected(self, client):
        resp = client.post("/api/scan", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403

    def test_local_origin_allowed(self, client):
        assert client.get("/api/status", headers={"Origin": "http://127.0.0.1:8080"}).status_code == 200


def test_rollback_recipe_never_uses_shell(tmp_path):
    """A file name with shell metacharacters must round-trip untouched."""
    journal = Journal(tmp_path / "j.db")
    manager = BackupManager(tmp_path / "b", journal)
    nasty = tmp_path / "it's; rm -rf $(x).txt"
    nasty.write_text("original")
    backup = manager.backup_file(str(nasty))
    nasty.write_text("changed")
    assert manager.restore(backup.backup_path)
    assert nasty.read_text() == "original"
    assert Path(backup.backup_path).exists()
