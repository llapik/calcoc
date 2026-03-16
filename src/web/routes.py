"""Flask API routes and web endpoints."""

import json
import uuid

from flask import Flask, request, jsonify, render_template, Response, stream_with_context

from src.core.config import Config
from src.core.logger import get_logger
from src.diagnostics.collector import SystemCollector
from src.analysis.problems import analyze_all
from src.analysis.performance import analyze as analyze_performance
from src.ai.engine import AIEngine
from src.ai.prompts import build_context_message
from src.safety.classifier import SafetyClassifier
from src.upgrade.advisor import analyze as analyze_upgrade

log = get_logger("web.routes")

_ALLOWED_LANGUAGES = frozenset({"ru", "en"})
_MAX_CHAT_MESSAGE_LEN = 4096


def register_routes(app: Flask) -> None:
    """Register all routes on the Flask app."""

    # In-memory session state (single-user local app)
    state: dict = {
        "snapshot": None,
        "problems": None,
        "session_id": str(uuid.uuid4())[:8],
    }

    def _config() -> Config:
        return app.config["CALCOC_CONFIG"]

    def _engine() -> AIEngine:
        return app.config["AI_ENGINE"]

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    @app.route("/")
    def index():
        config = _config()
        return render_template(
            "index.html",
            app_name=config.app_name,
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
            collector = SystemCollector()
            snapshot = collector.collect_all()
            state["snapshot"] = snapshot
            state["problems"] = None  # invalidate stale problem cache
            return jsonify({
                "status": "ok",
                "summary": snapshot.summary_text(),
                "data": snapshot.to_dict(),
            })
        except Exception as exc:
            log.exception("Scan failed")
            return jsonify({"status": "error", "message": "Ошибка диагностики. Подробности в журнале."}), 500

    @app.route("/api/problems", methods=["POST"])
    def api_problems():
        """Analyze system for problems."""
        if state["snapshot"] is None:
            return jsonify({"status": "error", "message": "Сначала выполните диагностику (/scan)"}), 400

        try:
            problems = analyze_all(state["snapshot"])
            state["problems"] = problems
            return jsonify({
                "status": "ok",
                "summary": problems.summary,
                "problems": [
                    {
                        "id": p.id,
                        "title": p.title,
                        "description": p.description,
                        "severity": p.severity.value,
                        "category": p.category,
                        "auto_fixable": p.auto_fixable,
                        "fix_action": p.fix_action,
                    }
                    for p in problems.problems
                ],
            })
        except Exception as exc:
            log.exception("Problem analysis failed")
            return jsonify({"status": "error", "message": "Ошибка анализа. Подробности в журнале."}), 500

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
            log.exception("Performance analysis failed")
            return jsonify({"status": "error", "message": "Ошибка анализа производительности. Подробности в журнале."}), 500

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
            log.exception("Upgrade analysis failed")
            return jsonify({"status": "error", "message": "Ошибка рекомендаций. Подробности в журнале."}), 500

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
        if len(message) > _MAX_CHAT_MESSAGE_LEN:
            return jsonify({"status": "error", "message": "Сообщение слишком длинное (макс. 4096 символов)"}), 400
        engine = _engine()
        context = _build_context(state)

        try:
            response = engine.chat(message, context=context)
            return jsonify({"status": "ok", "response": response, "backend": engine.backend_name})
        except Exception as exc:
            log.exception("Chat error")
            return jsonify({"status": "error", "message": "Ошибка AI. Подробности в журнале."}), 500

    @app.route("/api/chat/stream", methods=["POST"])
    def api_chat_stream():
        """Stream AI response via Server-Sent Events."""
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"status": "error", "message": "Сообщение не указано"}), 400

        message = data["message"]
        if len(message) > _MAX_CHAT_MESSAGE_LEN:
            return jsonify({"status": "error", "message": "Сообщение слишком длинное (макс. 4096 символов)"}), 400
        engine = _engine()
        context = _build_context(state)

        def generate():
            try:
                for token in engine.chat_stream(message, context=context):
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as exc:
                log.exception("Stream error")
                yield f"data: {json.dumps({'error': 'Ошибка AI. Подробности в журнале.'})}\n\n"

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

        if "language" in data and data["language"] in _ALLOWED_LANGUAGES:
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
