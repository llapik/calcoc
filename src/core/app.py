"""Main application entry-point for AI PC Repair & Optimizer."""

import argparse
import secrets
from pathlib import Path

from flask import Flask

from src.core.config import Config
from src.core.logger import setup_logging, get_logger
from src.web.routes import register_routes
from src.ai.engine import AIEngine

_SRC_DIR = Path(__file__).resolve().parent.parent

log = get_logger("app")


def create_app(config: Config | None = None) -> Flask:
    """Build and return the Flask application."""
    if config is None:
        config = Config()

    setup_logging(log_dir=config.settings.get("paths", {}).get("logs_dir"))

    app = Flask(
        __name__,
        template_folder=str(_SRC_DIR / "web" / "templates"),
        static_folder=str(_SRC_DIR / "web" / "static"),
    )
    app.config["SECRET_KEY"] = secrets.token_hex(32)
    app.config["CALCOC_CONFIG"] = config

    # Initialise AI engine (lazy — actual model loaded on first request)
    engine = AIEngine(config)
    app.config["AI_ENGINE"] = engine

    register_routes(app)

    log.info("Application created  backend=%s  lang=%s", config.ai_backend, config.language)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="AI PC Repair & Optimizer")
    parser.add_argument("--host", default=None, help="Web server bind address")
    parser.add_argument("--port", type=int, default=None, help="Web server port")
    parser.add_argument("--config-dir", default=None, help="Path to config directory")
    parser.add_argument("--expert", action="store_true", help="Enable expert mode")
    args = parser.parse_args()

    config = Config(config_dir=args.config_dir)
    if args.expert:
        config.settings.setdefault("app", {})["expert_mode"] = True

    app = create_app(config)
    host = args.host or config.web_host
    port = args.port or config.web_port
    log.info("Starting web server on %s:%s", host, port)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
