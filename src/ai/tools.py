"""Tools the AI agent can call.

The agent can look at anything (scan, problems, component details, journal, knowledge base) but it
can never modify the machine by itself: ``propose_fix`` and ``propose_rollback`` only put a
confirmation card in front of the user, and the change runs through ``RepairExecutor`` when the
user clicks it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Callable

from src.core.logger import get_logger
from src.core.session import AppSession, SessionError
from src.rollback.backup import BackupManager
from src.upgrade.advisor import analyze as analyze_upgrade

if TYPE_CHECKING:
    from src.ai.rag import KnowledgeBase

log = get_logger("ai.tools")

_COMPONENTS = ("cpu", "memory", "disk", "gpu", "motherboard", "os", "network")
_MAX_RESULT_CHARS = 6000


@dataclass
class ToolResult:
    content: str                                       # what the model reads
    events: list[dict] = field(default_factory=list)   # extra things the UI should show
    state_changed: bool = False                        # UI panels need a refresh
    ok: bool = True


def _spec(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


TOOL_SPECS: list[dict] = [
    _spec("scan_system",
          "Run a full hardware and software diagnostic scan of the PC and analyse it for problems. "
          "Returns a system summary and the list of detected problems. Call this first if no scan exists yet, "
          "or again to re-check after changes."),
    _spec("list_problems",
          "List currently detected problems with id, severity, whether an automatic fix exists, its risk level "
          "and whether it is available right now."),
    _spec("get_component_details",
          "Get full raw diagnostic data for one component, e.g. every S.M.A.R.T. attribute of the disks or "
          "the installed memory modules.",
          {"component": {"type": "string", "enum": list(_COMPONENTS)}}, ["component"]),
    _spec("propose_fix",
          "Offer the user an automatic fix for a detected problem. This does NOT run the fix: the user sees a "
          "confirmation card with the risk level and decides. Use the problem id from list_problems.",
          {"problem_id": {"type": "string", "description": "Problem id such as P002"}}, ["problem_id"]),
    _spec("get_upgrade_advice",
          "Get hardware upgrade recommendations for this PC, ordered by priority, with expected effect and cost."),
    _spec("get_journal",
          "List recent operations performed on this PC (fixes, rollbacks) with their status."),
    _spec("propose_rollback",
          "Offer the user to undo a completed operation from the journal. Does NOT undo it by itself.",
          {"journal_id": {"type": "integer"}}, ["journal_id"]),
    _spec("search_knowledge",
          "Search the built-in PC repair knowledge base for troubleshooting steps.",
          {"query": {"type": "string"}}, ["query"]),
]


class Toolbox:
    """Executes tool calls against the application session."""

    def __init__(self, session: AppSession, knowledge: KnowledgeBase | None = None):
        self.session = session
        self.knowledge = knowledge
        self._tools: dict[str, Callable[..., ToolResult]] = {
            "scan_system": self._scan_system,
            "list_problems": self._list_problems,
            "get_component_details": self._get_component_details,
            "propose_fix": self._propose_fix,
            "get_upgrade_advice": self._get_upgrade_advice,
            "get_journal": self._get_journal,
            "propose_rollback": self._propose_rollback,
            "search_knowledge": self._search_knowledge,
        }

    def call(self, name: str, arguments: str | dict | None) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(f"Unknown tool: {name}", ok=False)
        try:
            args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else (arguments or {})
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
            result = tool(**args)
        except SessionError as exc:
            return ToolResult(exc.message("en"), ok=False)
        except (TypeError, ValueError) as exc:
            return ToolResult(f"Bad arguments for {name}: {exc}", ok=False)
        except Exception as exc:
            log.exception("Tool %s failed", name)
            return ToolResult(f"Tool {name} failed: {exc}", ok=False)
        if len(result.content) > _MAX_RESULT_CHARS:
            result.content = result.content[:_MAX_RESULT_CHARS] + "\n…(truncated)"
        return result

    # ------------------------------------------------------------------
    def _scan_system(self) -> ToolResult:
        snapshot = self.session.scan()
        self.session.analyze()
        return ToolResult(
            f"{snapshot.summary_text()}\n\n{self._problems_text()}",
            state_changed=True,
        )

    def _list_problems(self) -> ToolResult:
        if self.session.snapshot is None:
            return ToolResult("No scan yet. Call scan_system first.", ok=False)
        return ToolResult(self._problems_text())

    def _problems_text(self) -> str:
        problems = self.session.problems_json()
        if not problems:
            return "No problems detected."
        lines = [self.session.problems.summary]
        for p in problems:
            line = f"- {p['id']} [{p['severity']}] {p['title']} — {p['description']}"
            if p["status"] == "fixed":
                line += f" (FIXED in this session, journal entry #{p['journal_id']})"
            elif fix := p.get("fix"):
                available = "available" if fix["availability"] == "done" else f"not available: {fix['note']}"
                line += f" | automatic fix: {fix['plan']} (risk {fix['risk_level']}, {available})"
            else:
                line += " | no automatic fix"
            lines.append(line)
        return "\n".join(lines)

    def _get_component_details(self, component: str) -> ToolResult:
        if component not in _COMPONENTS:
            return ToolResult(f"Unknown component. Choose one of: {', '.join(_COMPONENTS)}", ok=False)
        if self.session.snapshot is None:
            return ToolResult("No scan yet. Call scan_system first.", ok=False)
        data = getattr(self.session.snapshot, component)
        if data is None:
            return ToolResult(f"No data was collected for {component}.", ok=False)
        payload = asdict(data)
        if component == "cpu":
            payload.pop("flags", None)  # hundreds of CPU feature flags are noise for the model
        return ToolResult(json.dumps(payload, ensure_ascii=False))

    def _propose_fix(self, problem_id: str) -> ToolResult:
        if self.session.snapshot is None:
            return ToolResult("No scan yet. Call scan_system first.", ok=False)
        self.session.ensure_problems()
        problem = self.session.find_problem(str(problem_id))
        plan = self.session.plan_repair(problem.id)
        if plan.status != "done":
            return ToolResult(f"The fix cannot be offered ({plan.status}): {plan.message}", ok=False)
        card = {
            "type": "fix_proposal",
            "problem_id": problem.key,  # the stable key: display ids change when the analysis reruns
            "title": problem.title,
            "plan": plan.plan,
            "note": plan.message,
            "risk_level": plan.risk_level,
            "risk_label": plan.risk_label,
            "requires_backup": plan.requires_backup,
        }
        return ToolResult(
            f"A confirmation card for {problem.id} is now shown to the user (risk: {plan.risk_level}). "
            f"What it will do: {plan.plan}. Nothing has been changed yet — the user decides. "
            "Do not say the fix was performed.",
            events=[card],
        )

    def _get_upgrade_advice(self) -> ToolResult:
        if self.session.snapshot is None:
            return ToolResult("No scan yet. Call scan_system first.", ok=False)
        return ToolResult(analyze_upgrade(self.session.snapshot).to_text())

    def _get_journal(self) -> ToolResult:
        entries = self.session.journal_json(limit=15)
        if not entries:
            return ToolResult("The journal is empty: no operations have been performed.")
        return ToolResult("\n".join(
            f"- #{e['id']} {e['action']} ({e['description']}) — {e['status']}"
            f"{', can be rolled back' if e['can_rollback'] else ''}"
            for e in entries
        ))

    def _propose_rollback(self, journal_id: int) -> ToolResult:
        entry = self.session.executor.journal.get_entry(int(journal_id))
        if entry is None or not BackupManager.can_rollback(entry):
            return ToolResult(f"Journal entry #{journal_id} cannot be rolled back.", ok=False)
        card = {
            "type": "rollback_proposal",
            "journal_id": entry.id,
            "title": self.session.executor.classifier.describe(entry.action) or entry.action,
        }
        return ToolResult(
            f"A confirmation card to roll back entry #{entry.id} is now shown to the user. Nothing changed yet.",
            events=[card],
        )

    def _search_knowledge(self, query: str) -> ToolResult:
        docs = self.knowledge.search(str(query), top_k=3) if self.knowledge else []
        if not docs:
            return ToolResult("Nothing relevant in the knowledge base.")
        return ToolResult("\n\n".join(f"## {d.get('title', '')}\n{d.get('content', '')}" for d in docs))
