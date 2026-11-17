# getting-ready

A Claude Code plugin. Say "get ready" and Claude:

1. Copies the PostHog repo into a new git worktree under `~/.worktrees/posthog/` (or clones it from GitHub when you are not in a checkout), with your `.env` files.
2. Installs dependencies with flox, or with `uv` and `pnpm` when flox is not installed.
3. Starts the dev stack with `hogli up -d` and waits until `http://localhost:8010` serves the app and reaches the database.
4. Creates a test workspace with demo data, logs a headless Chromium into it, and saves the session and a screenshot.
5. Reports the URL, login, and screenshot.

Everything the run produces is in `<worktree>/.getting-ready/`: `status.json`, `READY.md`, `workspace.json`, `storage-state.json`, and `smoke.png`.

## Install

From a PostHog checkout:

```bash
claude plugin marketplace add ./tools/claude-plugins
```

```bash
claude plugin install getting-ready@posthog-dev
```

## Requirements

Docker (OrbStack on macOS) must be running, and port 8010 must be free. If another worktree's stack holds the port, stop it there with `hogli down -y`. Without Docker, use a devbox instead (`hogli devbox:start --start-app`).

You can run the script without Claude:

```bash
bash tools/claude-plugins/getting-ready/scripts/get-ready.sh --help
```
