"""AI agent — a tool-calling loop on top of a chat backend.

The agent yields UI events while it works:

* ``{"type": "token", "text": ...}`` — a piece of the assistant's answer
* ``{"type": "tool_start", "id", "name"}`` / ``{"type": "tool_end", "id", "name", "ok"}``
* ``{"type": "fix_proposal", ...}`` / ``{"type": "rollback_proposal", ...}`` — confirmation cards
* ``{"type": "state_changed"}`` — scan results or problems changed, refresh the panels
* ``{"type": "error", "message"}`` and finally ``{"type": "done"}``
"""

from __future__ import annotations

from typing import Generator, Iterable, Protocol

from src.ai.prompts import get_agent_prompt
from src.ai.tools import TOOL_SPECS, Toolbox
from src.core.logger import get_logger
from src.core.session import AppSession

log = get_logger("ai.agent")

_MAX_STEPS = 6  # model round-trips per user message


class ChatBackend(Protocol):
    def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None,
        temperature: float = 0.3, max_tokens: int = 2048,
    ) -> Iterable[dict]:
        """Yield ``{"type": "token", "text"}`` events, then one ``{"type": "message", "message"}``."""


class Agent:
    def __init__(self, backend: ChatBackend, session: AppSession, toolbox: Toolbox,
                 temperature: float = 0.3, max_tokens: int = 2048):
        self.backend = backend
        self.session = session
        self.toolbox = toolbox
        self.temperature = temperature
        self.max_tokens = max_tokens

    def run(self, user_message: str) -> Generator[dict, None, None]:
        session = self.session
        notes = session.take_notes()
        content = user_message
        if notes:
            content = "[Events in the app since your last reply]\n" + "\n".join(f"- {n}" for n in notes) \
                + f"\n\n{user_message}"

        turn: list[dict] = [{"role": "user", "content": content}]
        system = {"role": "system", "content": get_agent_prompt(session.lang, self._situation())}

        try:
            for step in range(_MAX_STEPS):
                last_step = step == _MAX_STEPS - 1
                message = None
                for event in self.backend.chat_stream(
                    [system, *session.history, *turn],
                    tools=None if last_step else TOOL_SPECS,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                ):
                    if event["type"] == "token":
                        yield event
                    elif event["type"] == "message":
                        message = event["message"]
                if message is None:
                    raise RuntimeError("the model returned no message")

                turn.append(message)
                calls = message.get("tool_calls") or []
                if not calls:
                    break

                for call in calls:
                    name = call["function"]["name"]
                    yield {"type": "tool_start", "id": call["id"], "name": name}
                    result = self.toolbox.call(name, call["function"].get("arguments"))
                    yield {"type": "tool_end", "id": call["id"], "name": name, "ok": result.ok}
                    yield from result.events
                    if result.state_changed:
                        yield {"type": "state_changed"}
                    turn.append({"role": "tool", "tool_call_id": call["id"], "content": result.content})
        except Exception as exc:
            log.exception("Agent run failed")
            yield {"type": "error", "message": str(exc)}
            # keep only what forms a valid conversation: the user's message and any finished exchange
            turn = _drop_dangling_tool_calls(turn)

        session.remember(turn)
        yield {"type": "done"}

    def _situation(self) -> str:
        s = self.session
        mode = f"Run mode: {s.config.mode}"
        if s.demo:
            mode += f" (DEMO scenario: {s.demo.title('en')}; repairs act on a sandbox)"
        parts = [mode, f"Expert mode: {'on' if s.config.expert_mode else 'off'}"]
        if s.snapshot is None:
            parts.append("No diagnostic scan has been run yet.")
        else:
            parts.append("A diagnostic scan exists. " + (s.problems.summary if s.problems else ""))
        return "\n".join(parts)


def _drop_dangling_tool_calls(turn: list[dict]) -> list[dict]:
    """Trim a failed turn so every assistant tool call has its tool result."""
    while turn and turn[-1]["role"] != "user":
        last = turn[-1]
        if last["role"] == "assistant" and not last.get("tool_calls"):
            break
        if last["role"] == "tool":
            # complete only if all calls of the preceding assistant message are answered
            i = len(turn) - 1
            while turn[i]["role"] == "tool":
                i -= 1
            answered = {m["tool_call_id"] for m in turn[i + 1:]}
            if {c["id"] for c in turn[i].get("tool_calls", [])} <= answered:
                break
        turn.pop()
    return turn
