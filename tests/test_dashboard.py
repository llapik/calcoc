"""Tests for the health dashboard model, telemetry history, predictions and translations."""

import re
import sqlite3
import time
from pathlib import Path

import pytest

from src.core import i18n
from src.core.app import create_app
from src.core.config import Config
from src.diagnostics.collector import SystemSnapshot
from src.diagnostics.cpu import CPUInfo
from src.diagnostics.disk import DiskDevice, DiskInfo, SmartAttribute
from src.telemetry.collector import TelemetryCollector, TelemetryRecord, snapshot_to_record
from src.telemetry.predictor import predict_records, slope_per_month

SCENARIOS = ["dying_hdd", "overheating_laptop", "infected_office", "broken_boot", "healthy"]
DAY = 86400
CYRILLIC = re.compile("[а-яё]", re.IGNORECASE)


@pytest.fixture
def make_session(monkeypatch):
    monkeypatch.setenv("AI_BACKEND", "none")

    def make(demo=None, lang="ru"):
        monkeypatch.setenv("APP_LANGUAGE", lang)
        app = create_app(Config(), demo=demo)
        return app.config["SESSION"], app.test_client()
    return make


class TestHealth:
    def test_healthy_pc_scores_100(self, make_session):
        session, _ = make_session("healthy")
        session.scan()
        health = session.health_json()
        assert health["score"] == 100 and health["status"] == "good"
        assert {c["status"] for c in health["components"]} == {"good"}

    def test_failing_disk_card_is_critical_and_lists_its_problems(self, make_session):
        session, _ = make_session("dying_hdd")
        session.scan()
        health = session.health_json()
        cards = {c["id"]: c for c in health["components"]}
        disk = cards["disk:/dev/sda"]
        assert disk["status"] == "critical" and health["status"] == "critical"
        assert {p["key"] for p in disk["problems"]} >= {"smart_failing:/dev/sda", "logs:io_errors"}
        assert disk["table"]["row_status"][0] == "critical"  # Reallocated_Sector_Ct below threshold
        assert cards["cpu"]["status"] == "good" and cards["memory"]["status"] == "warning"
        assert 0 < health["score"] < 40

    def test_meters_stay_within_bounds(self, make_session):
        for scenario in SCENARIOS:
            session, _ = make_session(scenario)
            session.scan()
            for card in session.health_json()["components"]:
                for meter in card["meters"]:
                    assert 0 <= meter["percent"] <= 100, (scenario, card["id"], meter)
                    assert meter["status"] in ("good", "warning", "serious", "critical")

    def test_score_improves_after_a_fix_and_drops_back_on_rollback(self, make_session):
        session, _ = make_session("infected_office")
        session.scan()
        before = session.health_json()
        outcome = session.repair("malware:miner", confirm=True)
        after = session.health_json()
        assert after["score"] > before["score"]
        cpu = next(c for c in after["components"] if c["id"] == "cpu")
        assert cpu["status"] == "good"  # the miner was what kept the CPU busy and hot
        session.rollback(outcome.journal_id)
        assert session.health_json()["score"] == before["score"]

    def test_api_requires_a_scan(self, make_session):
        _, client = make_session("healthy")
        assert client.get("/api/health").status_code == 404
        assert client.get("/api/history").status_code == 404
        client.post("/api/scan")
        assert client.get("/api/health").get_json()["health"]["score"] == 100


class TestHistory:
    def test_demo_history_charts_the_dying_disk(self, make_session):
        session, _ = make_session("dying_hdd")
        session.scan()
        history = session.history_json()
        series = {s["id"]: s for s in history["series"]}
        realloc = series["realloc:/dev/sda"]["points"]
        assert realloc[0][1] == 0 and realloc[-1][1] == 1864  # ends at the current snapshot
        assert [p[0] for p in realloc] == sorted(p[0] for p in realloc)
        assert "gpu_temp" not in series  # no sensor data, so no empty chart
        risks = [p["risk"] for p in history["predictions"]]
        assert risks == sorted(risks, key=["critical", "high", "medium", "low"].index) and risks[0] == "critical"

    def test_fix_shows_up_as_the_latest_point(self, make_session):
        session, _ = make_session("infected_office")
        session.scan()
        before = {s["id"]: s for s in session.history_json()["series"]}["cpu_temp"]["points"][-1][1]
        session.repair("malware:miner", confirm=True)
        after = {s["id"]: s for s in session.history_json()["series"]}["cpu_temp"]["points"][-1][1]
        assert after < before

    def test_real_scans_are_recorded_but_not_more_often_than_the_interval(self, tmp_path):
        telemetry = TelemetryCollector(tmp_path / "t.db")
        snapshot = SystemSnapshot(cpu=CPUInfo(model="X", temperature_c=50))
        assert telemetry.record(snapshot, min_interval=600) is True
        assert telemetry.record(snapshot, min_interval=600) is False
        assert telemetry.record(snapshot) is True
        assert len(telemetry.get_history(TelemetryCollector.machine_id(snapshot))) == 2

    def test_old_database_gains_the_wear_column(self, tmp_path):
        db = tmp_path / "old.db"
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TABLE telemetry (id INTEGER PRIMARY KEY, timestamp REAL, machine_id TEXT, cpu_temp REAL, "
                "cpu_usage REAL, ram_usage_pct REAL, disk_temps TEXT, smart_status TEXT, power_on_hours TEXT, "
                "gpu_temp REAL)"
            )
            conn.execute("INSERT INTO telemetry (timestamp, machine_id, cpu_temp) VALUES (1, 'm', 40)")
        telemetry = TelemetryCollector(db)
        assert telemetry.get_history("m")[0].per_disk("smart_attrs") == {}
        telemetry.record(SystemSnapshot(cpu=CPUInfo(model="X")), machine_id="m")
        assert len(telemetry.get_history("m")) == 2

    def test_snapshot_record_keeps_wear_counters(self):
        disk = DiskDevice(device="/dev/sda", smart_healthy=True, temperature_c=40, smart_attrs=[
            SmartAttribute(id=5, raw_value="12"), SmartAttribute(id=194, raw_value="40 (Min/Max 20/50)"),
            SmartAttribute(id=197, raw_value="n/a"),
        ])
        record = snapshot_to_record(SystemSnapshot(disk=DiskInfo(devices=[disk])), timestamp=1.0)
        assert record.per_disk("smart_attrs") == {"/dev/sda": {"5": 12}}
        assert record.per_disk("disk_temps") == {"/dev/sda": 40}


def _records(values, **column):
    """One record per value, 30 days apart; *column* names what the values are."""
    (name, build), = column.items()
    return [TelemetryRecord(timestamp=i * 30 * DAY, **{name: build(v)}) for i, v in enumerate(values)]


class TestPredictor:
    def test_slope_is_measured_against_time_not_scan_count(self):
        dense = [(i * DAY, 50 + i) for i in range(5)]            # +1 °C per day
        sparse = [(i * 30 * DAY, 50 + i) for i in range(5)]      # +1 °C per month
        assert slope_per_month(dense) == pytest.approx(30)
        assert slope_per_month(sparse) == pytest.approx(1)
        assert slope_per_month([(0, 5)]) == 0 and slope_per_month([(7, 1), (7, 9)]) == 0

    def test_growing_reallocated_sectors_are_flagged(self):
        history = _records([0, 8, 40, 200], smart_attrs=lambda v: f'{{"/dev/sda": {{"5": {v}}}}}')
        kinds = {p.kind: p for p in predict_records(history).predictions}
        assert kinds["realloc_growing"].risk == "critical" and "200" in kinds["realloc_growing"].description

    def test_stable_reallocated_sectors_are_only_watched(self):
        history = _records([8, 8, 8], smart_attrs=lambda v: f'{{"/dev/sda": {{"5": {v}}}}}')
        (prediction,) = predict_records(history).predictions
        assert prediction.kind == "realloc_present" and prediction.risk == "medium"

    def test_rising_cpu_temperature(self):
        report = predict_records(_records([60, 64, 69, 75, 83], cpu_temp=float))
        assert [p.kind for p in report.predictions] == ["cpu_temp_rising"] and report.predictions[0].risk == "high"

    def test_a_few_minutes_of_scans_are_not_a_trend(self):
        history = [TelemetryRecord(timestamp=i * 60, cpu_temp=50 + i * 3) for i in range(5)]
        assert predict_records(history).predictions == []

    def test_too_little_data(self):
        report = predict_records([TelemetryRecord(timestamp=time.time(), cpu_temp=95)], "en")
        assert report.predictions == [] and "two scans" in report.summary


class TestTranslations:
    def test_backend_catalogue_has_both_languages(self):
        incomplete = [k for k, v in i18n._MESSAGES.items() if not (v.get("ru") and "en" in v)]
        assert incomplete == []

    def test_frontend_catalogue_keys_match(self):
        source = Path("src/web/static/js/i18n.js").read_text(encoding="utf-8")
        ru_block, en_block = source.split("    en: {")
        keys = lambda block: set(re.findall(r"^\s+'([\w.]+)':", block, re.MULTILINE))  # noqa: E731
        assert keys(ru_block) == keys(en_block) and len(keys(ru_block)) > 100

    def test_frontend_uses_only_defined_keys(self):
        source = Path("src/web/static/js/i18n.js").read_text(encoding="utf-8")
        defined = set(re.findall(r"^\s+'([\w.]+)':", source, re.MULTILINE))
        js = Path("src/web/static/js/app.js").read_text(encoding="utf-8")
        html = Path("src/web/templates/index.html").read_text(encoding="utf-8")
        used = set(re.findall(r"\bT\('([\w.]+)'[,)]", js))
        used |= set(re.findall(r'data-(?:i18n(?:-title|-placeholder)?|suggest|ask)="([\w.]+)"', html + js))
        assert used - defined == set()

    def test_english_mode_has_no_russian_in_server_texts(self, make_session):
        for scenario in SCENARIOS:
            session, client = make_session(scenario, lang="en")
            client.post("/api/scan")
            texts = [client.post("/api/problems").get_data(as_text=True)]
            texts += [client.get(url).get_data(as_text=True) for url in ("/api/health", "/api/history")]
            for problem in session.problems_json():
                if problem.get("fix"):
                    client.post("/api/repair", json={"problem_id": problem["key"], "confirm": True})
            texts.append(client.get("/api/journal").get_data(as_text=True))
            for text in texts:
                decoded = text.encode().decode("unicode_escape", errors="ignore") if "\\u" in text else text
                assert not CYRILLIC.search(decoded), (scenario, CYRILLIC.search(decoded))

    def test_switching_language_retranslates_problems(self, make_session):
        _, client = make_session("dying_hdd", lang="ru")
        client.post("/api/scan")
        assert CYRILLIC.search(client.post("/api/problems").get_json()["summary"])
        client.post("/api/settings", json={"language": "en"})
        assert not CYRILLIC.search(client.get("/api/problems").get_json()["summary"])
