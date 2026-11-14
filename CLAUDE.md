# CLAUDE.md

This file provides guidance for AI assistants working in this repository.

## Project Overview

**Name:** AI PC Repair & Optimizer (`calcoc`)
**Repository:** `llapik/calcoc`
**Language:** Python 3.10+ with Bash scripts
**Framework:** Flask (web), llama-cpp-python (AI inference)

Bootable USB-based tool (256 GB) with local AI for PC diagnostics, repair, optimization, and upgrade recommendations. Supports hardware from Pentium 4 to modern PCs. Features a web chat interface with Russian/English support.

## Repository Structure

```
calcoc/
├── CLAUDE.md                    # This file
├── README.md                    # Project overview
├── Makefile                     # Build/dev commands
├── requirements.txt             # Python dependencies
├── .gitignore
├── config/
│   ├── grub/grub.cfg            # GRUB bootloader menu
│   ├── settings.yaml            # Main app config
│   ├── models.yaml              # AI model tiers by RAM
│   └── safety_rules.yaml        # Risk levels & action rules
├── scripts/
│   ├── build_iso.sh             # Build bootable ISO
│   ├── install_to_usb.sh        # Write to USB drive
│   └── setup_env.sh             # Dev environment setup
├── src/
│   ├── core/                    # App entry, config, logging
│   │   ├── app.py               # Flask app factory & CLI
│   │   ├── config.py            # YAML config loader, data-dir path resolution
│   │   ├── platform.py          # OS family, run mode (desktop/rescue), data dir
│   │   ├── session.py           # AppSession: scan/problems/repair state shared by API and agent
│   │   ├── i18n.py              # Backend message catalogue (ru/en)
│   │   └── logger.py            # Logging setup
│   ├── demo/
│   │   └── scenarios.py         # Demo scenarios ("sick PCs") + sandbox
│   ├── diagnostics/             # Hardware/software info collection
│   │   ├── cpu.py               # /proc/cpuinfo + sensors
│   │   ├── memory.py            # /proc/meminfo + dmidecode
│   │   ├── disk.py              # S.M.A.R.T. via smartctl
│   │   ├── gpu.py               # lspci + nvidia-smi
│   │   ├── motherboard.py       # dmidecode
│   │   ├── os_info.py           # Detect installed OSes
│   │   ├── network.py           # Interfaces, connectivity
│   │   └── collector.py         # Aggregates all diagnostics
│   ├── analysis/                # Problem detection
│   │   ├── log_analyzer.py      # System log error patterns
│   │   ├── performance.py       # Bottleneck detection
│   │   ├── malware.py           # ClamAV integration
│   │   ├── problems.py          # Unified problem report
│   │   └── health.py            # Dashboard model: score, component cards, meters
│   ├── ai/                      # AI inference layer
│   │   ├── engine.py            # Unified AI facade
│   │   ├── agent.py             # Tool-calling loop, yields UI events
│   │   ├── tools.py             # Tools the agent may call (read-only + proposals)
│   │   ├── llama_backend.py     # Local GGUF via llama-cpp-python
│   │   ├── openrouter.py        # OpenRouter cloud API
│   │   ├── model_selector.py    # Pick model by available RAM
│   │   ├── rag.py               # Knowledge base retrieval
│   │   └── prompts.py           # System/context prompts
│   ├── repair/                  # Auto-fix modules
│   │   ├── executor.py          # THE repair path: safety → backup → action → journal
│   │   ├── filesystem.py        # e2fsck, ntfsfix
│   │   ├── bootloader.py        # GRUB/BCD/MBR repair
│   │   ├── registry.py          # Offline Windows registry
│   │   ├── cleanup.py           # Temp file removal
│   │   └── antivirus.py         # Quarantine/remove malware
│   ├── rollback/                # Undo system
│   │   ├── backup.py            # File/MBR/partition backups
│   │   └── journal.py           # SQLite operation journal
│   ├── telemetry/               # Historical data
│   │   ├── collector.py         # Record snapshots to DB
│   │   └── predictor.py         # Failure trend analysis
│   ├── safety/
│   │   └── classifier.py        # Risk-level gating
│   ├── upgrade/
│   │   └── advisor.py           # Upgrade recommendations
│   └── web/                     # Web interface
│       ├── routes.py            # Flask API endpoints
│       ├── templates/index.html # Single-page chat UI
│       └── static/
│           ├── css/style.css    # Dark theme styles
│           └── js/
│               ├── i18n.js      # UI strings (ru/en), T() and data-i18n
│               └── app.js       # Frontend logic: chat, dashboard, charts
├── data/
│   ├── components_db.json       # Hardware price database
│   ├── demo/*.json              # Demo scenarios (snapshot + problems + sandbox files)
│   └── knowledge/
│       └── common_fixes.json    # RAG knowledge base
└── tests/
    ├── test_config.py
    ├── test_safety.py
    ├── test_rollback.py
    ├── test_diagnostics.py
    ├── test_ai_engine.py
    ├── test_telemetry.py
    ├── test_repair.py           # End-to-end repair pipeline via demo scenarios
    ├── test_agent.py            # Agent loop with a scripted model, toolbox, stream parser
    └── test_dashboard.py        # Health model, telemetry history, predictions, translations
```

## Development Setup

```bash
# Create venv and install dependencies
bash scripts/setup_env.sh
# or
make setup

# Activate venv
source .venv/bin/activate

# Run the web app (http://127.0.0.1:8080)
python -m src.core.app
# or
make run

# Run tests
make test
# or
pytest tests/ -v

# Lint
make lint
```

## Key Commands

| Command | Description |
|---------|-------------|
| `make setup` | Create venv + install deps |
| `make run` | Start web server on :8080 |
| `make demo` | Start with a demo scenario (sandboxed repairs) |
| `make test` | Run pytest |
| `make lint` | Run flake8 |
| `make build` | Build bootable ISO |
| `make install-usb USB_DEV=/dev/sdX` | Write to USB |
| `make clean` | Remove build artifacts |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENROUTER_API_KEY` | API key for OpenRouter cloud backend |
| `AI_BACKEND` | Override AI backend (`llama`, `openrouter`, `none`) |
| `APP_LANGUAGE` | UI language (`ru`, `en`) |
| `CALCOC_MODE` | `rescue` when booted from the USB stick; default `desktop` |
| `CALCOC_DATA_DIR` | Override the data directory (journal, backups, logs) |
| `CALCOC_DEMO` | Start with this demo scenario id |

## Architecture Conventions

### AI Backend Selection
The system dynamically selects an AI model based on available RAM (see `config/models.yaml`):
- < 2 GB RAM: AI disabled, rules-only mode
- 2-4 GB: SmolLM 135M
- 4-8 GB: Phi-3 Mini 3.8B
- 8-16 GB: LLaMA 3 8B (Q4)
- 16+ GB: LLaMA 3 8B (Q6) with GPU offload

OpenRouter can be used as an alternative when internet is available; it is also used automatically
when no local model fits and a key is configured.

### AI agent
With a tool-calling backend (currently OpenRouter) chat runs through `Agent` (`src/ai/agent.py`). Its
tools (`src/ai/tools.py`) are read-only plus `propose_fix` / `propose_rollback`, which only show the user
a confirmation card — the model must never get a tool that modifies the machine directly. Confirmed
actions go through `AppSession.repair()` and are reported to the model on its next turn.
Backends without tool calling fall back to plain chat with the scan summary as context.

### Safety System
Every repair action has a risk level defined in `config/safety_rules.yaml`:
- **green** — read-only, no confirmation needed
- **yellow** — reversible changes, confirmation + backup required
- **red** — risky changes, expert mode or elevated permissions needed
- **black** — blocked by default (e.g. BIOS flash), expert mode only

### Run modes
- **desktop** — the app runs inside a live OS (Linux, Windows planned). Only actions safe on a running system.
- **rescue** — booted from the USB stick; offline repairs (fsck, bootloader, registry) belong here.
- **demo** — a scenario from `data/demo` replaces the real machine; repairs act on a sandbox under the data dir.

### Repair pipeline
`RepairExecutor.execute()` (`src/repair/executor.py`) is the only entry point for modifications:
safety check → confirmation → backup → handler → journal entry. Handler arguments come from
server-side `Problem.fix_params`, never from the client. New repair actions are added as handlers there.

### Rollback
All modifications are journaled in SQLite (`src/rollback/journal.py`). Before any change a backup is created in the data directory. Each journal entry stores a JSON rollback recipe executed in Python by `BackupManager.rollback_entry()` — never a shell command.

### Web API Patterns
All API routes are in `src/web/routes.py`:
- `POST /api/scan` — full system diagnostic
- `POST /api/problems` — analyze for problems
- `POST /api/chat` — AI chat (JSON)
- `POST /api/chat/stream` — AI chat (SSE stream of agent events: token, tool_start/end, fix_proposal, …)
- `GET /api/scan`, `GET /api/problems` — last results without re-running
- `GET /api/health` — dashboard model (score, component cards, meters)
- `GET /api/history` — telemetry series for charts + trend predictions
- `POST /api/safety/check` — check action risk level
- `POST /api/upgrade` — upgrade recommendations
- `POST /api/repair` — fix a problem by id (`dry_run` for the plan, `confirm` to execute)
- `GET /api/journal`, `POST /api/journal/<id>/rollback` — operation journal and undo
- `POST /api/backups/purge` — delete stored backups
- `GET/POST /api/demo` — list / select demo scenarios
- `GET /api/status` — current session status
- `GET/POST /api/settings` — view/update settings

## Git Workflow

### Branches
- `master` — primary branch; never push directly
- `claude/<session-id>` — Claude Code session branches

### Rules
1. Always develop on a feature branch.
2. Claude branch names must start with `claude/` and match the session ID.
3. Commit messages should explain *why*, not just *what*.
4. Push with tracking: `git push -u origin <branch-name>`.
5. Retry on network failure: up to 4 times with exponential backoff (2s, 4s, 8s, 16s).

## Code Style

- Python 3.10+ — use `|` union types, dataclasses, pathlib
- Max line length: 120 characters
- Linter: flake8
- Test framework: pytest
- Config format: YAML
- Database: SQLite (via stdlib sqlite3)
- Logging: stdlib `logging` via `src/core/logger.get_logger(name)`

## Working Guidelines

- Read existing code before modifying it.
- Session state lives in `AppSession`; routes and agent tools call it rather than keeping their own state.
- Never commit API keys; UI-entered settings are stored in `<data_dir>/user_settings.yaml`.
- Every repair action must go through `RepairExecutor` (which calls `SafetyClassifier.check()`); never call repair modules directly from routes or AI code.
- Every destructive operation must create a backup via `BackupManager` first.
- Never recommend BIOS flashing without explicit user consent + backup.
- All user-facing text should support Russian (primary) and English: backend strings go through
  `src/core/i18n.t()`, UI strings through `T()` in `static/js/i18n.js`; `safety_rules.yaml` and demo
  scenarios carry both languages. Tests fail if a key is missing in one language. (Known gap: the
  upgrade advisor and the AI system prompts for local models are still Russian-only.)
- Dashboard thresholds and statuses are decided server-side in `analysis/health.py` and
  `analysis/performance.py`; the frontend only draws. Status colours (good/warning/serious/critical)
  always come with an icon and a label.
- Predictions describe trends (what grows, how fast); never invent a failure date.
- GGUF model files (*.gguf) are never committed to git — they live on the USB data partition.
