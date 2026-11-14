"""Shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Keep journal, backups and demo sandboxes out of the developer's real data directory."""
    monkeypatch.setenv("CALCOC_DATA_DIR", str(tmp_path / "calcoc-data"))
    monkeypatch.delenv("CALCOC_MODE", raising=False)
    monkeypatch.delenv("CALCOC_DEMO", raising=False)
