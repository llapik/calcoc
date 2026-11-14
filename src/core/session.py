"""Application session — the state one user works with, shared by the web API and the AI agent.

Single-user local app, so there is exactly one session per process. Everything that reads or
changes that state (scan, analysis, repair, rollback, demo switching) goes through here, which
keeps the HTTP routes and the agent's tools from drifting apart.
"""

from __future__ import annotations

import uuid

from src.analysis.problems import Problem, ProblemReport, analyze_all
from src.core.config import Config
from src.core.i18n import t
from src.core.logger import get_logger
from src.demo.scenarios import DemoSession
from src.diagnostics.collector import SystemCollector, SystemSnapshot
from src.repair.executor import RepairExecutor, RepairOutcome
from src.rollback.backup import BackupManager

log = get_logger("session")

_MAX_HISTORY = 40  # chat messages kept for the AI (tool calls and results included)


class SessionError(Exception):
    """A request that cannot be served in the current state; carries an i18n key and HTTP code."""

    def __init__(self, key: str, code: int = 400, **fmt):
        super().__init__(key)
        self.key, self.code, self.fmt = key, code, fmt

    def message(self, lang: str) -> str:
        return t(self.key, lang, **self.fmt)


class AppSession:
    def __init__(self, config: Config, executor: RepairExecutor, demo: str | None = None):
        self.config = config
        self.executor = executor
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
        return self.snapshot

    def analyze(self) -> ProblemReport:
        if self.snapshot is None:
            raise SessionError("scan.required")
        if self.demo is not None:
            self.snapshot = self.demo.snapshot()
            self.problems = analyze_all(self.snapshot, host_checks=False, extra=self.demo.problems(self.lang))
        else:
            self.problems = analyze_all(self.snapshot)
        return self.problems

    def ensure_problems(self) -> ProblemReport:
        return self.problems if self.problems is not None else self.analyze()

    def find_problem(self, ref: str) -> Problem:
        """Look up an open problem by its stable key or by its display id.

        Display ids (P001…) are renumbered whenever the analysis reruns, so anything that outlives
        one render — a confirmation card in the chat, for instance — must use the key.
        """
        candidates = [p for p in self.problems.problems if p.key not in self.fixed] if self.problems else []
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
