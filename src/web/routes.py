"""Flask API routes and web endpoints."""

import json
import uuid
from urllib.parse import urlsplit

from flask import Flask, request, jsonify, render_template, Response, stream_with_context, abort

from src.core import platform
from src.core.config import Config
from src.core.i18n import t
from src.core.logger import get_logger
from src.demo.scenarios import DemoSession, list_scenarios
from src.repair.executor import RepairExecutor
from src.rollback.backup import BackupManager
from src.diagnostics.collector import SystemCollector
from src.analysis.problems import analyze_all, Problem
from src.analysis.performance import analyze as analyze_performance
from src.ai.engine import AIEngine
from src.ai.prompts import build_context_message
from src.safety.classifier import SafetyClassifier
from src.upgrade.advisor import analyze as analyze_upgrade

log = get_logger("web.routes")


def register_routes(app: Flask) -> None:
    """Register all routes on the Flask app."""

    # In-memory session state (single-user local app)
    state: dict = {
        "snapshot": None,
        "problems": None,
        "fixed": {},  # problem key -> {"problem": Problem, "journal_id": int}
        "demo": None,  # DemoSession when a demo scenario is loaded
        "session_id": str(uuid.uuid4())[:8],
    }

    def _config() -> Config:
        return app.config["CALCOC_CONFIG"]

    def _engine() -> AIEngine:
        return app.config["AI_ENGINE"]

    def _executor() -> RepairExecutor:
        return app.config["REPAIR_EXECUTOR"]

    def _lang() -> str:
        return _config().language

    def _error(key: str, code: int = 400, **fmt):
        return jsonify({"status": "error", "message": t(key, _lang(), **fmt)}), code

    def _load_demo(scenario_id: str | None) -> None:
        """Switch to a demo scenario (or back to the real machine) and reset session results."""
        config = _config()
        demo = DemoSession(config.demo_dir, scenario_id, config.data_dir / "demo_sandbox") if scenario_id else None
        state.update(demo=demo, snapshot=None, problems=None, fixed={})
        _executor().demo = demo

    def _analyze() -> None:
        demo: DemoSession | None = state["demo"]
        if demo is not None:
            state["snapshot"] = demo.snapshot()
            state["problems"] = analyze_all(state["snapshot"], host_checks=False, extra=demo.problems(_lang()))
        else:
            state["problems"] = analyze_all(state["snapshot"])

    def _find_problem(problem_id: str) -> Problem | None:
        report = state["problems"]
        return next((p for p in report.problems if p.id == problem_id), None) if report else None

    def _problem_json(p: Problem, journal_id: int | None = None) -> dict:
        data = {
            "id": p.id,
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
            plan = _executor().plan(p.fix_action)
            data["fix"] = {
                "risk_level": plan.risk_level,
                "risk_label": plan.risk_label,
                "availability": plan.status,  # done = can run now
                "note": plan.message,
            }
        return data

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

    if scenario := app.config.get("DEMO_SCENARIO"):
        _load_demo(scenario)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    @app.route("/")
    def index():
        config = _config()
        return render_template(
            "index.html",
            app_name=config.app_name,
            demo_id=state["demo"].id if state["demo"] else "",
            scenarios=list_scenarios(config.demo_dir, config.language),
            language=config.language,
            ai_backend=_engine().backend_name,
            expert_mode=config.expert_mode,
        )

    # ------------------------------------------------------------------
    # API: System diagnostics
    # ------------------------------------------------------------------
    @app.route("/api/scan", methods=["POST"])
    def api_scan():
        """Run full system diagnostic scan."""
        try:
            demo: DemoSession | None = state["demo"]
            snapshot = demo.snapshot() if demo else SystemCollector().collect_all()
            state["snapshot"] = snapshot
            state["problems"] = None  # invalidate stale problem cache
            return jsonify({
                "status": "ok",
                "summary": snapshot.summary_text(),
                "data": snapshot.to_dict(),
            })
        except Exception as exc:
            log.error("Scan failed: %s", exc)
            return jsonify({"status": "error", "message": f"Ошибка диагностики: {exc}"}), 500

    @app.route("/api/problems", methods=["POST"])
    def api_problems():
        """Analyze system for problems."""
        if state["snapshot"] is None:
            return jsonify({"status": "error", "message": "Сначала выполните диагностику (/scan)"}), 400

        try:
            _analyze()
            problems = state["problems"]
            open_problems = [p for p in problems.problems if p.key not in state["fixed"]]
            fixed = [(f["problem"], f["journal_id"]) for f in state["fixed"].values()]
            return jsonify({
                "status": "ok",
                "summary": problems.summary,
                "problems": [_problem_json(p) for p in open_problems]
                + [_problem_json(p, journal_id) for p, journal_id in fixed],
            })
        except Exception as exc:
            log.exception("Problem analysis failed")
            return jsonify({"status": "error", "message": f"Ошибка анализа: {exc}"}), 500

    @app.route("/api/performance", methods=["POST"])
    def api_performance():
        """Run performance analysis."""
        if state["snapshot"] is None:
            return jsonify({"status": "error", "message": "Сначала выполните диагностику (/scan)"}), 400

        try:
            report = analyze_performance(state["snapshot"])
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
        except Exception as exc:
            log.error("Performance analysis failed: %s", exc)
            return jsonify({"status": "error", "message": f"Ошибка: {exc}"}), 500

    @app.route("/api/upgrade", methods=["POST"])
    def api_upgrade():
        """Get upgrade recommendations."""
        if state["snapshot"] is None:
            return jsonify({"status": "error", "message": "Сначала выполните диагностику (/scan)"}), 400

        try:
            report = analyze_upgrade(state["snapshot"])
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
        except Exception as exc:
            log.error("Upgrade analysis failed: %s", exc)
            return jsonify({"status": "error", "message": f"Ошибка: {exc}"}), 500

    # ------------------------------------------------------------------
    # API: AI Chat
    # ------------------------------------------------------------------
    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        """Send a message to the AI assistant (blocking)."""
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"status": "error", "message": "Сообщение не указано"}), 400

        message = data["message"]
        engine = _engine()
        context = _build_context(state)

        try:
            response = engine.chat(message, context=context)
            return jsonify({"status": "ok", "response": response, "backend": engine.backend_name})
        except Exception as exc:
            log.error("Chat error: %s", exc)
            return jsonify({"status": "error", "message": str(exc)}), 500

    @app.route("/api/chat/stream", methods=["POST"])
    def api_chat_stream():
        """Stream AI response via Server-Sent Events."""
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"status": "error", "message": "Сообщение не указано"}), 400

        message = data["message"]
        engine = _engine()
        context = _build_context(state)

        def generate():
            try:
                for token in engine.chat_stream(message, context=context):
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as exc:
                log.error("Stream error: %s", exc)
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------
    # API: Repair — safety check → backup → action → journal
    # ------------------------------------------------------------------
    @app.route("/api/repair", methods=["POST"])
    def api_repair():
        """Fix a detected problem. The action and its arguments come from server-side state only."""
        data = request.get_json(silent=True) or {}
        problem = _find_problem(str(data.get("problem_id", "")))
        if problem is None:
            return _error("problem.not_found", 404)
        if not problem.fix_action:
            return _error("problem.not_fixable")

        executor = _executor()
        if data.get("dry_run"):
            return jsonify({"status": "ok", "outcome": executor.plan(problem.fix_action).to_dict()})

        outcome = executor.execute(
            problem.fix_action,
            params=problem.fix_params,
            confirmed=bool(data.get("confirm")),
            session_id=state["session_id"],
        )
        if outcome.ok and outcome.journal_id is not None:
            state["fixed"][problem.key] = {"problem": problem, "journal_id": outcome.journal_id}
            if state["demo"] is not None:
                state["demo"].fixed.add(problem.key)
                _analyze()  # the scenario's snapshot reflects the fix
        return jsonify({"status": "ok", "outcome": outcome.to_dict()})

    # ------------------------------------------------------------------
    # API: Journal and rollback
    # ------------------------------------------------------------------
    @app.route("/api/journal", methods=["GET"])
    def api_journal():
        executor = _executor()
        return jsonify({
            "status": "ok",
            "entries": [
                {
                    "id": e.id,
                    "timestamp": e.timestamp,
                    "action": e.action,
                    "description": executor.classifier.describe(e.action),
                    "target": e.target,
                    "risk_level": e.risk_level,
                    "status": e.status,
                    "can_rollback": BackupManager.can_rollback(e),
                    "details": e.details,
                    "this_session": e.session_id == state["session_id"],
                }
                for e in executor.journal.get_recent(limit=100)
            ],
        })

    @app.route("/api/journal/<int:entry_id>/rollback", methods=["POST"])
    def api_rollback(entry_id: int):
        executor = _executor()
        entry = executor.journal.get_entry(entry_id)
        if entry is None or not BackupManager.can_rollback(entry):
            return _error("rollback.not_possible", 409, id=entry_id)
        if not executor.rollback(entry_id):
            return _error("rollback.failed", 500, id=entry_id)

        # The problem this operation fixed is open again
        for key, fixed in list(state["fixed"].items()):
            if fixed["journal_id"] == entry_id:
                del state["fixed"][key]
                if state["demo"] is not None:
                    state["demo"].fixed.discard(key)
        if state["demo"] is not None and state["snapshot"] is not None:
            _analyze()
        return jsonify({"status": "ok", "message": t("rollback.done", _lang(), id=entry_id)})

    @app.route("/api/backups/purge", methods=["POST"])
    def api_backups_purge():
        """Delete stored backups to release disk space; purged operations cannot be undone."""
        count, released = _executor().backups.purge()
        state["fixed"] = {}
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
        return jsonify({
            "status": "ok",
            "active": state["demo"].id if state["demo"] else None,
            "scenarios": list_scenarios(config.demo_dir, config.language),
        })

    @app.route("/api/demo", methods=["POST"])
    def api_demo_select():
        """Load a demo scenario, or pass ``{"scenario": null}`` to return to the real machine."""
        scenario = (request.get_json(silent=True) or {}).get("scenario")
        try:
            _load_demo(str(scenario) if scenario else None)
        except KeyError:
            return _error("demo.unknown", 404)
        return jsonify({"status": "ok", "active": state["demo"].id if state["demo"] else None})

    # ------------------------------------------------------------------
    # API: Safety
    # ------------------------------------------------------------------
    @app.route("/api/safety/check", methods=["POST"])
    def api_safety_check():
        """Check if an action is safe to perform."""
        data = request.get_json()
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
            "ai_model": engine.model_name,
            "ai_available": engine.is_available,
        })

    @app.route("/api/settings", methods=["POST"])
    def api_settings_post():
        data = request.get_json() or {}
        config = _config()
        engine = _engine()

        if "language" in data:
            config.settings.setdefault("app", {})["language"] = data["language"]
        if "expert_mode" in data:
            config.settings.setdefault("app", {})["expert_mode"] = bool(data["expert_mode"])
        if "ai_backend" in data and data["ai_backend"] in ("llama", "openrouter", "none"):
            engine.switch_backend(data["ai_backend"])

        return jsonify({"status": "ok"})

    # ------------------------------------------------------------------
    # API: Status
    # ------------------------------------------------------------------
    @app.route("/api/status", methods=["GET"])
    def api_status():
        engine = _engine()
        return jsonify({
            "status": "ok",
            "session_id": state["session_id"],
            "has_scan": state["snapshot"] is not None,
            "has_problems": state["problems"] is not None,
            "mode": _config().mode,
            "platform": platform.os_family(),
            "demo": state["demo"].id if state["demo"] else None,
            "ai_backend": engine.backend_name,
            "ai_model": engine.model_name,
            "ai_available": engine.is_available,
        })


# ------------------------------------------------------------------
# Helpers (module-level, not closures)
# ------------------------------------------------------------------
def _build_context(state: dict) -> str:
    """Build AI context string from current session state."""
    if state["snapshot"] is None:
        return ""
    system_info = state["snapshot"].summary_text()
    problems_text = state["problems"].summary if state["problems"] else ""
    return build_context_message(system_info, problems_text, "")
