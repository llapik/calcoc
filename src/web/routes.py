"""Flask API routes and web endpoints."""

import json
from urllib.parse import urlsplit

from flask import Flask, request, jsonify, render_template, Response, stream_with_context, abort

from src.ai.agent import Agent
from src.ai.engine import AIEngine
from src.ai.prompts import build_context_message
from src.ai.tools import Toolbox
from src.analysis.performance import analyze as analyze_performance
from src.core import platform
from src.core.config import Config
from src.core.i18n import t
from src.core.logger import get_logger
from src.core.session import AppSession, SessionError
from src.demo.scenarios import list_scenarios
from src.safety.classifier import SafetyClassifier
from src.upgrade.advisor import analyze as analyze_upgrade

log = get_logger("web.routes")


def register_routes(app: Flask) -> None:
    """Register all routes on the Flask app."""

    def _config() -> Config:
        return app.config["CALCOC_CONFIG"]

    def _engine() -> AIEngine:
        return app.config["AI_ENGINE"]

    def _session() -> AppSession:
        return app.config["SESSION"]

    def _lang() -> str:
        return _config().language

    def _error(key: str, code: int = 400, **fmt):
        return jsonify({"status": "error", "message": t(key, _lang(), **fmt)}), code

    @app.errorhandler(SessionError)
    def _session_error(exc: SessionError):
        return jsonify({"status": "error", "message": exc.message(_lang())}), exc.code

    @app.before_request
    def _guard_local_requests():
        """Refuse cross-site and DNS-rebinding requests: this API can modify the machine."""
        host = _config().web_host
        if host in ("0.0.0.0", "::"):
            return  # deliberately exposed (rescue image); nothing to compare against
        allowed = {"localhost", "127.0.0.1", "[::1]", "::1", host}
        if urlsplit(f"//{request.host}").hostname not in allowed:
            abort(403)
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).hostname not in allowed:
            abort(403)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    @app.route("/")
    def index():
        config = _config()
        session = _session()
        return render_template(
            "index.html",
            app_name=config.app_name,
            demo_id=session.demo.id if session.demo else "",
            scenarios=list_scenarios(config.demo_dir, config.language),
            language=config.language,
            ai_backend=_engine().backend_name,
            expert_mode=config.expert_mode,
        )

    # ------------------------------------------------------------------
    # API: System diagnostics
    # ------------------------------------------------------------------
    def _scan_json(snapshot):
        return jsonify({"status": "ok", "summary": snapshot.summary_text(), "data": snapshot.to_dict()})

    @app.route("/api/scan", methods=["POST"])
    def api_scan():
        """Run full system diagnostic scan."""
        try:
            return _scan_json(_session().scan())
        except Exception as exc:
            log.exception("Scan failed")
            return jsonify({"status": "error", "message": f"Ошибка диагностики: {exc}"}), 500

    @app.route("/api/scan", methods=["GET"])
    def api_scan_cached():
        """Return the last scan without running a new one."""
        snapshot = _session().snapshot
        if snapshot is None:
            return _error("scan.required", 404)
        return _scan_json(snapshot)

    @app.route("/api/problems", methods=["POST"])
    def api_problems():
        """Analyze system for problems."""
        session = _session()
        report = session.analyze()
        return jsonify({"status": "ok", "summary": report.summary, "problems": session.problems_json()})

    @app.route("/api/problems", methods=["GET"])
    def api_problems_cached():
        """Return the current problem list without re-running the analysis."""
        session = _session()
        if session.snapshot is None:
            return _error("scan.required", 404)
        report = session.ensure_problems()
        return jsonify({"status": "ok", "summary": report.summary, "problems": session.problems_json()})

    @app.route("/api/performance", methods=["POST"])
    def api_performance():
        """Run performance analysis."""
        snapshot = _session().snapshot
        if snapshot is None:
            return _error("scan.required")
        report = analyze_performance(snapshot)
        return jsonify({
            "status": "ok",
            "score": report.score,
            "summary": report.summary,
            "bottlenecks": [
                {
                    "component": b.component,
                    "severity": b.severity,
                    "description": b.description,
                    "recommendation": b.recommendation,
                }
                for b in report.bottlenecks
            ],
        })

    @app.route("/api/upgrade", methods=["POST"])
    def api_upgrade():
        """Get upgrade recommendations."""
        snapshot = _session().snapshot
        if snapshot is None:
            return _error("scan.required")
        report = analyze_upgrade(snapshot)
        return jsonify({
            "status": "ok",
            "text": report.to_text(),
            "bottlenecks": report.bottlenecks,
            "recommendations": [
                {
                    "component": r.component,
                    "priority": r.priority,
                    "current": r.current,
                    "recommended": r.recommended,
                    "reason": r.reason,
                    "expected_impact": r.expected_impact,
                    "estimated_cost": r.estimated_cost,
                }
                for r in report.recommendations
            ],
        })

    # ------------------------------------------------------------------
    # API: Repair — safety check → backup → action → journal
    # ------------------------------------------------------------------
    @app.route("/api/repair", methods=["POST"])
    def api_repair():
        """Fix a detected problem (``dry_run`` returns the plan, ``confirm`` executes)."""
        data = request.get_json(silent=True) or {}
        problem_id = str(data.get("problem_id", ""))
        session = _session()
        if data.get("dry_run"):
            outcome = session.plan_repair(problem_id)
        else:
            outcome = session.repair(problem_id, confirm=bool(data.get("confirm")))
        return jsonify({"status": "ok", "outcome": outcome.to_dict()})

    # ------------------------------------------------------------------
    # API: Journal and rollback
    # ------------------------------------------------------------------
    @app.route("/api/journal", methods=["GET"])
    def api_journal():
        return jsonify({"status": "ok", "entries": _session().journal_json()})

    @app.route("/api/journal/<int:entry_id>/rollback", methods=["POST"])
    def api_rollback(entry_id: int):
        _session().rollback(entry_id)
        return jsonify({"status": "ok", "message": t("rollback.done", _lang(), id=entry_id)})

    @app.route("/api/backups/purge", methods=["POST"])
    def api_backups_purge():
        """Delete stored backups to release disk space; purged operations cannot be undone."""
        count, released = _session().purge_backups()
        return jsonify({
            "status": "ok",
            "message": t("purge.done", _lang(), count=count, size_mb=released / (1024 * 1024)),
        })

    # ------------------------------------------------------------------
    # API: Demo scenarios
    # ------------------------------------------------------------------
    @app.route("/api/demo", methods=["GET"])
    def api_demo_list():
        config = _config()
        session = _session()
        return jsonify({
            "status": "ok",
            "active": session.demo.id if session.demo else None,
            "scenarios": list_scenarios(config.demo_dir, config.language),
        })

    @app.route("/api/demo", methods=["POST"])
    def api_demo_select():
        """Load a demo scenario, or pass ``{"scenario": null}`` to return to the real machine."""
        scenario = (request.get_json(silent=True) or {}).get("scenario")
        session = _session()
        session.load_demo(str(scenario) if scenario else None)
        return jsonify({"status": "ok", "active": session.demo.id if session.demo else None})

    # ------------------------------------------------------------------
    # API: AI Chat
    # ------------------------------------------------------------------
    def _chat_events(message: str):
        """Yield UI events for one chat turn: the agent when the backend can call tools, plain chat otherwise."""
        engine, session = _engine(), _session()
        backend = engine.agent_backend()
        if backend is not None:
            temperature, max_tokens = engine.sampling()
            agent = Agent(backend, session, Toolbox(session, engine.knowledge), temperature, max_tokens)
            yield from agent.run(message)
            return
        try:
            for token in engine.chat_stream(message, context=_build_context(session)):
                yield {"type": "token", "text": token}
        except Exception as exc:
            log.exception("Chat failed")
            yield {"type": "error", "message": str(exc)}
        yield {"type": "done"}

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        """Send a message to the AI assistant (blocking)."""
        data = request.get_json(silent=True)
        if not data or not data.get("message"):
            return jsonify({"status": "error", "message": "Сообщение не указано"}), 400

        text, events = [], []
        for event in _chat_events(str(data["message"])):
            if event["type"] == "token":
                text.append(event["text"])
            elif event["type"] == "error":
                return jsonify({"status": "error", "message": event["message"]}), 502
            elif event["type"] != "done":
                events.append(event)
        return jsonify({
            "status": "ok", "response": "".join(text), "events": events, "backend": _engine().backend_name,
        })

    @app.route("/api/chat/stream", methods=["POST"])
    def api_chat_stream():
        """Stream the AI's work via Server-Sent Events (see ``src/ai/agent.py`` for event types)."""
        data = request.get_json(silent=True)
        if not data or not data.get("message"):
            return jsonify({"status": "error", "message": "Сообщение не указано"}), 400
        message = str(data["message"])

        def generate():
            for event in _chat_events(message):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------
    # API: Safety
    # ------------------------------------------------------------------
    @app.route("/api/safety/check", methods=["POST"])
    def api_safety_check():
        """Check if an action is safe to perform."""
        data = request.get_json(silent=True)
        action = data.get("action", "") if data else ""
        if not action:
            return jsonify({"status": "error", "message": "Действие не указано"}), 400

        classifier = SafetyClassifier(_config())
        verdict = classifier.check(action)
        return jsonify({
            "status": "ok",
            "action": verdict.action,
            "risk_level": verdict.risk_level,
            "allowed": verdict.allowed,
            "reason": verdict.reason,
            "requires_confirmation": verdict.requires_confirmation,
            "requires_backup": verdict.requires_backup,
            "label": verdict.label,
            "color": classifier.get_risk_color(verdict.risk_level),
        })

    # ------------------------------------------------------------------
    # API: Settings — two separate functions, same URL, different methods
    # ------------------------------------------------------------------
    @app.route("/api/settings", methods=["GET"])
    def api_settings_get():
        config = _config()
        engine = _engine()
        return jsonify({
            "language": config.language,
            "expert_mode": config.expert_mode,
            "ai_backend": config.ai_backend,
            "ai_backend_active": engine.backend_name,
            "ai_model": engine.model_name,
            "ai_available": engine.is_available,
            "openrouter_model": config.openrouter_model,
            "openrouter_key_set": bool(config.openrouter_api_key),  # the key itself is never returned
        })

    @app.route("/api/settings", methods=["POST"])
    def api_settings_post():
        data = request.get_json(silent=True) or {}
        config = _config()
        engine = _engine()
        reload_ai = False

        if data.get("language") in ("ru", "en"):
            config.set_user("app", "language", data["language"])
        if "expert_mode" in data:
            config.settings.setdefault("app", {})["expert_mode"] = bool(data["expert_mode"])
        if isinstance(data.get("openrouter_api_key"), str) and data["openrouter_api_key"].strip():
            config.set_user("openrouter", "api_key", data["openrouter_api_key"].strip())
            reload_ai = True
        if isinstance(data.get("openrouter_model"), str) and data["openrouter_model"].strip():
            config.set_user("openrouter", "default_model", data["openrouter_model"].strip())
            reload_ai = True
        if data.get("ai_backend") in ("llama", "openrouter", "none"):
            config.set_user("ai", "backend", data["ai_backend"])
            reload_ai = True
        if reload_ai:
            engine.switch_backend(config.ai_backend)

        return jsonify({"status": "ok", "ai_backend_active": engine.backend_name, "ai_available": engine.is_available})

    # ------------------------------------------------------------------
    # API: Status
    # ------------------------------------------------------------------
    @app.route("/api/status", methods=["GET"])
    def api_status():
        engine = _engine()
        session = _session()
        return jsonify({
            "status": "ok",
            "session_id": session.id,
            "has_scan": session.snapshot is not None,
            "has_problems": session.problems is not None,
            "mode": _config().mode,
            "platform": platform.os_family(),
            "demo": session.demo.id if session.demo else None,
            "ai_backend": engine.backend_name,
            "ai_model": engine.model_name,
            "ai_available": engine.is_available,
            "ai_agent": engine.agent_backend() is not None,
        })


def _build_context(session: AppSession) -> str:
    """Context block for backends without tool calling."""
    if session.snapshot is None:
        return ""
    problems_text = session.problems.summary if session.problems else ""
    return build_context_message(session.snapshot.summary_text(), problems_text, "")
