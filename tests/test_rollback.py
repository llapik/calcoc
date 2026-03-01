"""Tests for rollback journal and backup system."""

import os
import time

import pytest

from src.rollback.journal import Journal, JournalEntry
from src.rollback.backup import BackupManager


@pytest.fixture
def journal(tmp_path):
    return Journal(tmp_path / "test_journal.db")


@pytest.fixture
def backup_manager(tmp_path, journal):
    return BackupManager(tmp_path / "backups", journal)


class TestJournal:
    def test_record_and_retrieve(self, journal):
        entry_id = journal.record(
            action="test_action",
            target="/dev/sda1",
            details="Testing",
            risk_level="green",
            session_id="test-session",
        )
        assert entry_id > 0

        entry = journal.get_entry(entry_id)
        assert entry is not None
        assert entry.action == "test_action"
        assert entry.target == "/dev/sda1"
        assert entry.risk_level == "green"
        assert entry.session_id == "test-session"

    def test_get_recent(self, journal):
        for i in range(5):
            journal.record(action=f"action_{i}", target=f"target_{i}")

        recent = journal.get_recent(limit=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0].action == "action_4"

    def test_update_status(self, journal):
        entry_id = journal.record(action="test", backup_path="/backup/test")
        journal.update_status(entry_id, "rolled_back")

        entry = journal.get_entry(entry_id)
        assert entry.status == "rolled_back"

    def test_get_rollbackable(self, journal):
        journal.record(action="a1", backup_path="/backup/a1")
        journal.record(action="a2", backup_path="")  # no backup
        journal.record(action="a3", backup_path="/backup/a3")

        rollbackable = journal.get_rollbackable()
        assert len(rollbackable) == 2
        assert all(e.backup_path != "" for e in rollbackable)

    def test_get_session_entries(self, journal):
        journal.record(action="a1", session_id="s1")
        journal.record(action="a2", session_id="s2")
        journal.record(action="a3", session_id="s1")

        entries = journal.get_session_entries("s1")
        assert len(entries) == 2
        assert all(e.session_id == "s1" for e in entries)


class TestBackupManager:
    def test_backup_file(self, backup_manager, tmp_path):
        # Create a test file
        test_file = tmp_path / "test_source.txt"
        test_file.write_text("Hello, backup!")

        backup = backup_manager.backup_file(str(test_file), session_id="test")
        assert os.path.isfile(backup.backup_path)
        assert backup.backup_type == "file"
        assert backup.size_bytes > 0

        # Verify backup content
        with open(backup.backup_path) as fh:
            assert fh.read() == "Hello, backup!"

    def test_backup_directory(self, backup_manager, tmp_path):
        # Create test directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("File 1")
        (test_dir / "file2.txt").write_text("File 2")

        backup = backup_manager.backup_directory(str(test_dir), session_id="test")
        assert os.path.isfile(backup.backup_path)
        assert backup.backup_path.endswith(".tar.gz")
        assert backup.backup_type == "directory"

    def test_restore_file(self, backup_manager, tmp_path):
        # Create, backup, modify, then restore
        test_file = tmp_path / "restore_test.txt"
        test_file.write_text("Original content")

        backup = backup_manager.backup_file(str(test_file), session_id="test")

        # Modify the original
        test_file.write_text("Modified content")
        assert test_file.read_text() == "Modified content"

        # Restore
        result = backup_manager.restore(backup.backup_path)
        assert result is True
        assert test_file.read_text() == "Original content"

    def test_rollback_last(self, backup_manager, tmp_path):
        test_file = tmp_path / "rollback_test.txt"
        test_file.write_text("Before change")

        backup_manager.backup_file(str(test_file), session_id="sess1")
        test_file.write_text("After change")

        result = backup_manager.rollback_last(session_id="sess1")
        assert result is True
        assert test_file.read_text() == "Before change"
