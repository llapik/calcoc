"""Application session — the state one user works with, shared by the web API and the AI agent.

Single-user local app, so there is exactly one session per process. Everything that reads or
changes that state (scan, analysis, repair, rollback, demo switching) goes through here, which
keeps the HTTP routes and the agent's tools from drifting apart.
"""

from __future__ import annotations

import uuid

from src.analysis import health
from src.analysis.problems import Problem, ProblemReport, analyze_all
from src.core.config import Config
from src.core.i18n import t
from src.core.logger import get_logger
from src.demo.scenarios import DemoSession
from src.diagnostics.collector import SystemCollector, SystemSnapshot
from src.repair.executor import RepairExecutor, RepairOutcome
from src.rollback.backup import BackupManager
from src.telemetry.collector import TelemetryCollector, snapshot_to_record
from src.telemetry.predictor import predict_records

log = get_logger("session")

_TELEMETRY_INTERVAL = 600  # seconds between stored measurements of the same machine
_MAX_HISTORY = 40  # chat messages kept for the AI (tool calls and results included)


class SessionError(Exception):
    """A request that cannot be served in the current state; carries an i18n key and HTTP code."""

    def __init__(self, key: str, code: int = 400, **fmt):
        super().__init__(key)
        self.key, self.code, self.fmt = key, code, fmt

    def message(self, lang: str) -> str:
        return t(self.key, lang, **self.fmt)


class AppSession:
    def __init__(
        self, config: Config, executor: RepairExecutor, demo: str | None = None,
        telemetry: TelemetryCollector | None = None,
    ):
        self.config = config
        self.executor = executor
        self.telemetry = telemetry
        self.id = str(uuid.uuid4())[:8]
        self.snapshot: SystemSnapshot | None = None
        self.problems: ProblemReport | None = None
        self.fixed: dict[str, dict] = {}  # problem key -> {"problem": Problem, "journal_id": int}
        self.demo: DemoSession | None = None
        self.history: list[dict] = []     # chat messages in OpenAI format
        self._notes: list[str] = []       # UI events the AI should learn about on its next turn
        if demo:
            self.load_demo(demo)

    @property
    def lang(self) -> str:
        return self.config.language

    # ------------------------------------------------------------------
    # Demo
    # ------------------------------------------------------------------
    def load_demo(self, scenario_id: str | None) -> None:
        """Switch to a demo scenario (or back to the real machine) and reset session results."""
        try:
            demo = (
                DemoSession(self.config.demo_dir, scenario_id, self.config.data_dir / "demo_sandbox")
                if scenario_id else None
            )
        except KeyError:
            raise SessionError("demo.unknown", 404) from None
        self.demo = self.executor.demo = demo
        self.snapshot = self.problems = None
        self.fixed = {}
        self.history, self._notes = [], []

    # ------------------------------------------------------------------
    # Diagnostics and analysis
    # ------------------------------------------------------------------
    def scan(self) -> SystemSnapshot:
        self.snapshot = self.demo.snapshot() if self.demo else SystemCollector().collect_all()
        self.problems = None  # stale after a new scan
        if self.demo is None and self.telemetry is not None:
            try:  # history is a bonus: never let it break a scan
                self.telemetry.record(self.snapshot, min_interval=_TELEMETRY_INTERVAL)
            except Exception as exc:
                log.warning("Telemetry not recorded: %s", exc)
        return self.snapshot

    def analyze(self) -> ProblemReport:
        if self.snapshot is None:
            raise SessionError("scan.required")
        if self.demo is not None:
            self.snapshot = self.demo.snapshot()
            self.problems = analyze_all(
                self.snapshot, host_checks=False, extra=self.demo.problems(self.lang), lang=self.lang,
            )
        else:
            self.problems = analyze_all(self.snapshot, lang=self.lang)
        return self.problems

    def ensure_problems(self) -> ProblemReport:
        return self.problems if self.problems is not None else self.analyze()

    def find_problem(self, ref: str) -> Problem:
        """Look up an open problem by its stable key or by its display id.

        Display ids (P001…) are renumbered whenever the analysis reruns, so anything that outlives
        one render — a confirmation card in the chat, for instance — must use the key.
        """
        if self.snapshot is None:
            raise SessionError("scan.required")
        candidates = [p for p in self.ensure_problems().problems if p.key not in self.fixed]
        problem = next((p for p in candidates if p.key == ref), None) \
            or next((p for p in candidates if p.id == ref), None)
        if problem is None:
            raise SessionError("problem.not_found", 404)
        return problem

    def problems_json(self) -> list[dict]:
        """Open problems followed by the ones fixed in this session."""
        report = self.ensure_problems()
        open_problems = [self._problem_json(p) for p in report.problems if p.key not in self.fixed]
        fixed = [self._problem_json(f["problem"], f["journal_id"]) for f in self.fixed.values()]
        return open_problems + fixed

    def _problem_json(self, p: Problem, journal_id: int | None = None) -> dict:
        data = {
            "id": p.id,
            "key": p.key,
            "title": p.title,
            "description": p.description,
            "severity": p.severity.value,
            "category": p.category,
            "auto_fixable": p.auto_fixable,
            "fix_action": p.fix_action,
            "status": "fixed" if journal_id is not None else "open",
            "journal_id": journal_id,
        }
        if p.fix_action and journal_id is None:
            plan = self.executor.plan(p.fix_action)
            data["fix"] = {
                "risk_level": plan.risk_level,
                "risk_label": plan.risk_label,
                "availability": plan.status,  # done = can run now
                "note": plan.message,
                "plan": plan.plan,
            }
        return data

    def health_json(self) -> dict:
        """Dashboard model: score, per-component status, meters and the problems behind them."""
        report = self.ensure_problems()
        open_problems = [p for p in report.problems if p.key not in self.fixed]
        return health.build(self.snapshot, open_problems, self.lang).to_dict()

    def history_json(self) -> dict:
        """Measurements over time plus what their trends say, for the dashboard charts."""
        if self.snapshot is None:
            raise SessionError("scan.required", 404)
        now = snapshot_to_record(self.snapshot)
        if self.demo is not None:
            records = self.demo.history(now.timestamp) + [now]
        elif self.telemetry is not None:
            records = self.telemetry.get_history(TelemetryCollector.machine_id(self.snapshot), limit=200)[::-1]
            if not records or now.timestamp - records[-1].timestamp > 1:
                records.append(now)  # the latest scan was too close to the previous one to be stored
        else:
            records = [now]

        lang = self.lang
        series: list[dict] = []

        def add(series_id: str, label: str, unit: str, points: list[tuple[float, float | None]]) -> None:
            points = [[round(ts * 1000), round(v, 1)] for ts, v in points if v is not None]
            if len(points) >= 2:
                series.append({"id": series_id, "label": label, "unit": unit, "points": points})

        add("cpu_temp", t("history.cpu_temp", lang), "°C", [(r.timestamp, r.cpu_temp) for r in records])
        add("gpu_temp", t("history.gpu_temp", lang), "°C", [(r.timestamp, r.gpu_temp) for r in records])
        add("ram", t("history.ram", lang), "%", [(r.timestamp, r.ram_usage_pct) for r in records])
        devices = sorted({dev for r in records for dev in r.per_disk("disk_temps") | r.per_disk("smart_attrs")})
        for dev in devices:
            realloc = [(r.timestamp, r.per_disk("smart_attrs").get(dev, {}).get("5")) for r in records]
            if any(v for _, v in realloc):
                add(f"realloc:{dev}", t("history.realloc", lang, dev=dev), t("history.unit.sectors", lang), realloc)
            add(f"disk_temp:{dev}", t("history.disk_temp", lang, dev=dev), "°C",
                [(r.timestamp, r.per_disk("disk_temps").get(dev)) for r in records])

        report = predict_records(records, lang)
        return {
            "data_points": report.data_points,
            "summary": report.summary,
            "series": series,
            "predictions": [
                {"component": p.component, "risk": p.risk, "description": p.description, "trend": p.trend}
                for p in report.predictions
            ],
        }

    # ------------------------------------------------------------------
    # Repair and rollback
    # ------------------------------------------------------------------
    def plan_repair(self, problem_id: str) -> RepairOutcome:
        problem = self.find_problem(problem_id)
        if not problem.fix_action:
            raise SessionError("problem.not_fixable")
        return self.executor.plan(problem.fix_action)

    def repair(self, problem_id: str, confirm: bool) -> RepairOutcome:
        """Fix a detected problem. Action and arguments come from server-side state only."""
        problem = self.find_problem(problem_id)
        if not problem.fix_action:
            raise SessionError("problem.not_fixable")
        outcome = self.executor.execute(
            problem.fix_action, params=problem.fix_params, confirmed=confirm, session_id=self.id,
        )
        if outcome.ok and outcome.journal_id is not None:
            self.fixed[problem.key] = {"problem": problem, "journal_id": outcome.journal_id}
            if self.demo is not None:
                self.demo.fixed.add(problem.key)
                self.analyze()  # the scenario's snapshot reflects the fix
        if confirm:
            self.note(f'User ran the fix for "{problem.title}": {outcome.status}. {outcome.message}'
                      + (f" Journal entry #{outcome.journal_id}." if outcome.journal_id else ""))
        return outcome

    def rollback(self, entry_id: int) -> None:
        entry = self.executor.journal.get_entry(entry_id)
        if entry is None or not BackupManager.can_rollback(entry):
            raise SessionError("rollback.not_possible", 409, id=entry_id)
        if not self.executor.rollback(entry_id):
            raise SessionError("rollback.failed", 500, id=entry_id)

        # The problem this operation fixed is open again
        for key, fixed in list(self.fixed.items()):
            if fixed["journal_id"] == entry_id:
                del self.fixed[key]
                if self.demo is not None:
                    self.demo.fixed.discard(key)
        if self.demo is not None and self.snapshot is not None:
            self.analyze()
        self.note(f"User rolled back journal entry #{entry_id} ({entry.action}).")

    def purge_backups(self) -> tuple[int, int]:
        result = self.executor.backups.purge()
        self.fixed = {}
        return result

    def journal_json(self, limit: int = 100) -> list[dict]:
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "action": e.action,
                "description": self.executor.classifier.describe(e.action),
                "target": e.target,
                "risk_level": e.risk_level,
                "status": e.status,
                "can_rollback": BackupManager.can_rollback(e),
                "details": e.details,
                "this_session": e.session_id == self.id,
            }
            for e in self.executor.journal.get_recent(limit=limit)
        ]

    # ------------------------------------------------------------------
    # Chat memory
    # ------------------------------------------------------------------
    def note(self, text: str) -> None:
        """Queue a UI event; it is prepended to the user's next chat message for the AI."""
        self._notes.append(text)

    def take_notes(self) -> list[str]:
        notes, self._notes = self._notes, []
        return notes

    def remember(self, messages: list[dict]) -> None:
        self.history.extend(messages)
        if len(self.history) > _MAX_HISTORY:
            cut = len(self.history) - _MAX_HISTORY
            # never start the window in the middle of a tool exchange
            while cut < len(self.history) and self.history[cut]["role"] != "user":
                cut += 1
            self.history = self.history[cut:]
