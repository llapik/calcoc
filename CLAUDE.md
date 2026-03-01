# CLAUDE.md

This file provides guidance for AI assistants (Claude Code and similar tools) working in this repository.

## Project Overview

**Name:** calcoc
**Status:** Early-stage / placeholder repository
**Repository:** `llapik/calcoc`

The project currently contains only a minimal README. No language, framework, build system, or source code has been established yet. This CLAUDE.md should be updated as the project evolves.

## Repository Structure

```
calcoc/
├── README.md     # Minimal project description
└── CLAUDE.md     # This file
```

## Git Workflow

### Branches

- `master` — primary branch; do not push directly without explicit permission
- `claude/<session-id>` — branches created by Claude Code sessions for isolated development

### Development Rules

1. **Always develop on a feature branch**, never directly on `master`.
2. **Branch naming for Claude sessions:** must start with `claude/` and end with the matching session ID (e.g. `claude/claude-md-mm7ht8y0h4p818ll-ccmQ0`). Pushes to branches not matching this pattern will fail with HTTP 403.
3. **Commit messages** should be clear and descriptive, explaining *why* a change was made, not just *what* changed.
4. **Push with upstream tracking:** always use `git push -u origin <branch-name>`.
5. **Retry on network failure:** if `git push` or `git fetch` fails due to a network error, retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s).

### Typical Workflow

```bash
# Checkout or create your working branch
git checkout -b claude/<session-id>

# Make changes, then stage and commit
git add <specific-files>
git commit -m "Descriptive message"

# Push to remote
git push -u origin claude/<session-id>
```

## Development Conventions (to be established)

As the project grows, document conventions here including:

- **Language / runtime** — to be determined
- **Package manager** — to be determined
- **Linting / formatting** — to be determined
- **Testing framework** — to be determined
- **Build system** — to be determined

When these are established, update this file with:
- How to install dependencies
- How to run the project locally
- How to run tests
- How to build for production
- Any environment variables or secrets required

## Working in This Repository

### Before Making Changes

- Read the task description carefully.
- Check existing files to understand the current state before adding or modifying anything.
- Prefer editing existing files over creating new ones unless a new file is clearly necessary.

### Code Quality

- Write minimal, focused code — only what is needed to satisfy the current task.
- Avoid over-engineering, premature abstractions, or speculative features.
- Do not add comments, docstrings, or type annotations to code you did not change.
- Do not introduce security vulnerabilities (SQL injection, XSS, command injection, etc.).

### File Management

- Do not create documentation files (*.md) unless explicitly requested.
- Do not leave temporary or debug files in the repository.
- Always confirm before deleting files or taking other irreversible actions.

## Updating This File

Keep this CLAUDE.md current as the project evolves. Whenever a significant structural decision is made (language choice, framework adoption, test setup, CI/CD configuration), update the relevant section above.
