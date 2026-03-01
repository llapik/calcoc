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
│   │   ├── config.py            # YAML config loader
│   │   └── logger.py            # Logging setup
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
│   │   └── problems.py          # Unified problem report
│   ├── ai/                      # AI inference layer
│   │   ├── engine.py            # Unified AI facade
│   │   ├── llama_backend.py     # Local GGUF via llama-cpp-python
│   │   ├── openrouter.py        # OpenRouter cloud API
│   │   ├── model_selector.py    # Pick model by available RAM
│   │   ├── rag.py               # Knowledge base retrieval
│   │   └── prompts.py           # System/context prompts
│   ├── repair/                  # Auto-fix modules
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
│           └── js/app.js        # Frontend logic
├── data/
│   ├── components_db.json       # Hardware price database
│   └── knowledge/
│       └── common_fixes.json    # RAG knowledge base
└── tests/
    ├── test_config.py
    ├── test_safety.py
    ├── test_rollback.py
    ├── test_diagnostics.py
    ├── test_ai_engine.py
    └── test_telemetry.py
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

## Architecture Conventions

### AI Backend Selection
The system dynamically selects an AI model based on available RAM (see `config/models.yaml`):
- < 2 GB RAM: AI disabled, rules-only mode
- 2-4 GB: SmolLM 135M
- 4-8 GB: Phi-3 Mini 3.8B
- 8-16 GB: LLaMA 3 8B (Q4)
- 16+ GB: LLaMA 3 8B (Q6) with GPU offload

OpenRouter can be used as an alternative when internet is available.

### Safety System
Every repair action has a risk level defined in `config/safety_rules.yaml`:
- **green** — read-only, no confirmation needed
- **yellow** — reversible changes, confirmation + backup required
- **red** — risky changes, expert mode or elevated permissions needed
- **black** — blocked by default (e.g. BIOS flash), expert mode only

### Rollback
All modifications are journaled in SQLite (`src/rollback/journal.py`). Before any file/disk change, a backup is created in the USB data partition. Operations can be undone via the journal.

### Web API Patterns
All API routes are in `src/web/routes.py`:
- `POST /api/scan` — full system diagnostic
- `POST /api/problems` — analyze for problems
- `POST /api/chat` — AI chat (JSON)
- `POST /api/chat/stream` — AI chat (SSE streaming)
- `POST /api/safety/check` — check action risk level
- `POST /api/upgrade` — upgrade recommendations
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
- Every repair action must go through `SafetyClassifier.check()` before execution.
- Every destructive operation must create a backup via `BackupManager` first.
- Never recommend BIOS flashing without explicit user consent + backup.
- All user-facing text should support Russian (primary) and English.
- GGUF model files (*.gguf) are never committed to git — they live on the USB data partition.
