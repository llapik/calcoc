"""Tests for the tool-calling agent, driven by a scripted stand-in for the model."""

import json

import pytest

from src.ai.agent import Agent, _drop_dangling_tool_calls
from src.ai.openrouter import OpenRouterBackend
from src.ai.tools import TOOL_SPECS, Toolbox
from src.core.app import create_app
from src.core.config import Config


def call(name, call_id="c1", **args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedBackend:
    """Replays prepared assistant messages and records what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def chat_stream(self, messages, tools=None, temperature=0.3, max_tokens=2048):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str):
            reply = {"role": "assistant", "content": reply}
        if reply.get("content"):
            yield {"type": "token", "text": reply["content"]}
        yield {"type": "message", "message": reply}


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setenv("AI_BACKEND", "none")
    return create_app(Config(), demo="dying_hdd").config["SESSION"]


def run(session, backend, text):
    events = list(Agent(backend, session, Toolbox(session)).run(text))
    answer = "".join(e["text"] for e in events if e["type"] == "token")
    return events, answer


def types(events):
    return [e["type"] for e in events]


class TestAgentLoop:
    def test_plain_answer(self, session):
        backend = ScriptedBackend("Привет!")
        events, answer = run(session, backend, "привет")
        assert answer == "Привет!" and types(events) == ["token", "done"]
        assert [m["role"] for m in session.history] == ["user", "assistant"]
        assert backend.requests[0]["tools"] == TOOL_SPECS
        assert backend.requests[0]["messages"][0]["role"] == "system"

    def test_scans_on_its_own_then_answers(self, session):
        backend = ScriptedBackend(
            {"role": "assistant", "content": "", "tool_calls": [call("scan_system")]},
            "Диск умирает.",
        )
        events, answer = run(session, backend, "что с компьютером?")
        assert types(events) == ["tool_start", "tool_end", "state_changed", "token", "done"]
        assert session.snapshot is not None and session.problems is not None
        tool_result = backend.requests[1]["messages"][-1]
        assert tool_result["role"] == "tool" and "S.M.A.R.T." in tool_result["content"]
        assert answer == "Диск умирает."
        assert [m["role"] for m in session.history] == ["user", "assistant", "tool", "assistant"]

    def test_propose_fix_shows_card_but_changes_nothing(self, session):
        session.scan()
        session.analyze()
        problem = next(p for p in session.problems_json() if p["fix_action"] == "clean_temp_files")
        junk = session.demo.sandbox / "junk"
        before = sorted(p for p in junk.rglob("*") if p.is_file())

        backend = ScriptedBackend(
            {"role": "assistant", "content": "", "tool_calls": [call("propose_fix", problem_id=problem["id"])]},
            "Подтвердите очистку в карточке.",
        )
        events, _ = run(session, backend, "почисти диск")
        card = next(e for e in events if e["type"] == "fix_proposal")
        assert card["problem_id"] == problem["key"] and card["risk_level"] == "yellow"
        assert sorted(p for p in junk.rglob("*") if p.is_file()) == before
        assert session.executor.journal.get_recent() == []

    def test_cards_survive_renumbering_after_another_fix(self, session):
        """Two cards are proposed; running the first renumbers problems, the second must still hit its own."""
        session.load_demo("infected_office")
        session.scan()
        session.analyze()
        by_action = {p["key"]: p for p in session.problems_json() if p.get("fix")}
        miner, trojan = by_action["malware:miner"], by_action["malware:trojan"]
        backend = ScriptedBackend(
            {"role": "assistant", "content": "", "tool_calls": [
                call("propose_fix", "a", problem_id=miner["id"]), call("propose_fix", "b", problem_id=trojan["id"]),
            ]},
            "Две карточки.",
        )
        events, _ = run(session, backend, "убери вирусы")
        cards = [e for e in events if e["type"] == "fix_proposal"]
        assert [c["problem_id"] for c in cards] == ["malware:miner", "malware:trojan"]

        assert session.repair(cards[0]["problem_id"], confirm=True).ok
        ids_after = {p["key"]: p["id"] for p in session.problems_json() if p["status"] == "open"}
        assert ids_after["malware:trojan"] != trojan["id"]  # renumbered, so the old id is now someone else
        outcome = session.repair(cards[1]["problem_id"], confirm=True)
        assert outcome.ok and outcome.details["files"] == 2
        with pytest.raises(Exception):
            session.repair(cards[1]["problem_id"], confirm=True)  # already fixed

    def test_blocked_fix_is_not_offered(self, session):
        session.load_demo("broken_boot")
        session.scan()
        session.analyze()
        boot = next(p for p in session.problems_json() if p["fix_action"] == "fix_bootloader")
        backend = ScriptedBackend(
            {"role": "assistant", "content": "", "tool_calls": [call("propose_fix", problem_id=boot["id"])]},
            "Нужен режим эксперта.",
        )
        events, _ = run(session, backend, "почини загрузчик")
        assert "fix_proposal" not in types(events)
        assert next(e for e in events if e["type"] == "tool_end")["ok"] is False
        assert "blocked" in backend.requests[1]["messages"][-1]["content"]

    def test_user_confirmation_reaches_the_model_next_turn(self, session):
        session.scan()
        session.analyze()
        problem = next(p for p in session.problems_json() if p["fix_action"] == "clean_temp_files")
        outcome = session.repair(problem["id"], confirm=True)
        assert outcome.ok

        backend = ScriptedBackend("Готово.")
        run(session, backend, "что дальше?")
        sent = backend.requests[0]["messages"][-1]["content"]
        assert "User ran the fix" in sent and f"#{outcome.journal_id}" in sent and sent.endswith("что дальше?")

    def test_bad_tool_and_bad_arguments_are_reported_to_model(self, session):
        backend = ScriptedBackend(
            {"role": "assistant", "content": "", "tool_calls": [
                call("format_disk", "a"),
                {"id": "b", "type": "function", "function": {"name": "get_component_details", "arguments": "{oops"}},
                call("get_component_details", "c", component="disk", extra=1),
            ]},
            "Извините.",
        )
        events, _ = run(session, backend, "x")
        assert [e["ok"] for e in events if e["type"] == "tool_end"] == [False, False, False]
        assert [m["role"] for m in backend.requests[1]["messages"][-3:]] == ["tool", "tool", "tool"]

    def test_step_limit_forces_a_final_answer(self, session):
        looping = {"role": "assistant", "content": "", "tool_calls": [call("list_problems")]}
        backend = ScriptedBackend(*[looping] * 5, "Итог.")
        events, answer = run(session, backend, "x")
        assert answer == "Итог." and backend.requests[-1]["tools"] is None and len(backend.requests) == 6

    def test_backend_error_keeps_history_valid(self, session):
        backend = ScriptedBackend(
            {"role": "assistant", "content": "", "tool_calls": [call("scan_system")]},
            RuntimeError("OpenRouter 429: rate limited"),
        )
        events, _ = run(session, backend, "x")
        assert next(e for e in events if e["type"] == "error")["message"] == "OpenRouter 429: rate limited"
        assert events[-1]["type"] == "done"
        assert [m["role"] for m in session.history] == ["user", "assistant", "tool"]

    def test_history_window_starts_at_a_user_message(self, session):
        for i in range(30):
            session.remember([
                {"role": "user", "content": str(i)},
                {"role": "assistant", "content": "", "tool_calls": [call("list_problems")]},
                {"role": "tool", "tool_call_id": "c1", "content": "…"},
                {"role": "assistant", "content": "ok"},
            ])
        assert len(session.history) <= 40 and session.history[0]["role"] == "user"


def test_drop_dangling_tool_calls():
    user = {"role": "user", "content": "x"}
    pending = {"role": "assistant", "content": "", "tool_calls": [call("a", "1"), call("b", "2")]}
    assert _drop_dangling_tool_calls([user, pending]) == [user]
    assert _drop_dangling_tool_calls([user, pending, {"role": "tool", "tool_call_id": "1", "content": ""}]) == [user]


class TestToolbox:
    def test_tools_need_a_scan(self, session):
        box = Toolbox(session)
        for name in ("list_problems", "get_upgrade_advice"):
            assert box.call(name, "{}").ok is False
        assert box.call("get_component_details", {"component": "disk"}).ok is False

    def test_component_details_and_journal(self, session):
        box = Toolbox(session)
        box.call("scan_system", "")
        disk = json.loads(box.call("get_component_details", '{"component": "disk"}').content)
        assert disk["devices"][0]["smart_attrs"][0]["name"] == "Reallocated_Sector_Ct"
        assert box.call("get_component_details", '{"component": "bios"}').ok is False
        assert "empty" in box.call("get_journal", None).content

    def test_propose_rollback_only_for_undoable_entries(self, session):
        box = Toolbox(session)
        box.call("scan_system", "")
        assert box.call("propose_rollback", {"journal_id": 99}).ok is False
        problem = next(p for p in session.problems_json() if p["fix_action"] == "clean_temp_files")
        outcome = session.repair(problem["id"], confirm=True)
        result = box.call("propose_rollback", {"journal_id": outcome.journal_id})
        assert result.ok and result.events[0]["type"] == "rollback_proposal"

    def test_every_spec_has_an_implementation(self, session):
        box = Toolbox(session)
        assert {s["function"]["name"] for s in TOOL_SPECS} == set(box._tools)


class _FakeResponse:
    status_code = 200
    encoding = None

    def __init__(self, chunks):
        self._chunks = chunks

    def iter_lines(self, decode_unicode=True):
        for chunk in self._chunks:
            yield "data: " + (chunk if isinstance(chunk, str) else json.dumps(chunk))


def test_openrouter_stream_assembles_text_and_split_tool_calls(monkeypatch):
    def delta(**d):
        return {"choices": [{"delta": d}]}

    chunks = [
        delta(content="При"), delta(content="вет"), ": keep-alive is skipped", {"choices": []},
        delta(tool_calls=[
            {"index": 0, "id": "call_1", "function": {"name": "get_component_details", "arguments": ""}},
        ]),
        delta(tool_calls=[{"index": 0, "function": {"arguments": '{"compo'}}]),
        delta(tool_calls=[{"index": 0, "function": {"arguments": 'nent": "disk"}'}},
                          {"index": 1, "id": "call_2", "function": {"name": "scan_system"}}]),
        "[DONE]",
    ]
    backend = OpenRouterBackend("key", default_model="m1", fallback_models=["m2"])
    sent = {}

    def fake_post(url, json=None, **kwargs):
        sent.update(json)
        return _FakeResponse(chunks)

    monkeypatch.setattr(backend._session, "post", fake_post)
    events = list(backend.chat_stream([{"role": "user", "content": "x"}], tools=TOOL_SPECS))

    assert "".join(e["text"] for e in events if e["type"] == "token") == "Привет"
    message = events[-1]["message"]
    assert message["content"] == "Привет"
    assert [(c["id"], c["function"]["name"], c["function"]["arguments"]) for c in message["tool_calls"]] == [
        ("call_1", "get_component_details", '{"component": "disk"}'), ("call_2", "scan_system", "{}"),
    ]
    assert sent["models"] == ["m1", "m2"] and "model" not in sent and sent["tools"] == TOOL_SPECS


def test_settings_persist_but_never_expose_the_key(monkeypatch):
    monkeypatch.setenv("AI_BACKEND", "none")
    client = create_app(Config()).test_client()
    client.post("/api/settings", json={"openrouter_api_key": "sk-or-test", "language": "en", "expert_mode": True})
    body = client.get("/api/settings").get_data(as_text=True)
    assert "sk-or-test" not in body and '"openrouter_key_set":true' in body.replace(" ", "")

    monkeypatch.delenv("AI_BACKEND")
    fresh = Config()
    assert fresh.openrouter_api_key == "sk-or-test" and fresh.language == "en"
    assert fresh.expert_mode is False  # never persisted
