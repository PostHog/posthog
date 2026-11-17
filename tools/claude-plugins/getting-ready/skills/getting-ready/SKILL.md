---
name: getting-ready
description: Copies the PostHog repo into a fresh worktree, boots the dev stack there, logs a browser into a seeded test workspace, and reports back when agents can browse and screenshot the app. Use when the user says "get ready", "getting ready", "get posthog ready", or asks for a fresh PostHog copy that is set up for browsing or screenshots.
---

# Getting ready

Get a clean PostHog copy running and a browser logged in, then tell the user it is ready. One script does the work. Your job is to start it, wait for it, and report.

## 1. Start the script in the background

The first boot takes several minutes, so run it with `run_in_background: true` and do not poll with `sleep`. You are notified when it exits.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/get-ready.sh"
```

Flags, only when the user asks for them:

- `--ref <git ref>` copies a branch or commit instead of `origin/master`.
- `--from <path>` copies a specific PostHog checkout. By default the script uses the checkout you are in, or clones from GitHub when you are not in one.
- `--name <dir>` names the worktree directory under `~/.worktrees/posthog/` (or `$POSTHOG_WORKTREE_BASE`).
- `--skip-stack` stops after the copy and dependency install.

Tell the user in one line that setup has started and where the worktree is going.

## 2. Read the result

The last stdout line, and `<worktree>/.getting-ready/status.json`, hold `state`, `phase`, and `detail`.

- **`ready` (exit 0)**: read `<worktree>/.getting-ready/READY.md` and `workspace.json`, look at `smoke.png` with the Read tool to confirm it shows the PostHog app and not an error page, then report.
- **`blocked` (exit 2)**: the host is missing something the script cannot fix, such as a stopped Docker daemon or another stack already holding port 8010. Pass the `detail` to the user with the fix it names. Do not stop another worktree's stack yourself.
- **`failed` (exit 1)**: read the background output and `.getting-ready/smoke.log` if it exists. For stack or migration failures, follow the troubleshooting in the repo's `run-posthog` skill. Fix what you can and rerun with a new `--name`. Report what failed if you cannot fix it.

## 3. Report back

Keep it short:

- **Ready**: the worktree path, the app URL (`<base_url>/project/<team_id>`), the login email and password `12345678`, and the smoke screenshot. Send the screenshot with SendUserFile when that tool exists.
- How other agents browse from here: load `.getting-ready/storage-state.json` as Playwright `storageState` to start logged in, or log in again in-page with the credentials in `workspace.json`. Use `personal_api_key` from `workspace.json` as `Authorization: Bearer <key>` for API calls.
- How to stop: `cd <worktree> && hogli down -y`.

## Browsing and screenshotting afterwards

- Browse `http://localhost:8010`, not Vite on `:8234`.
- Wait for a `[data-attr]` element before a screenshot. `networkidle` never settles because posthog-js and Vite HMR keep polling.
- Scene URLs live under `/project/<team_id>/`. The repo's `run-posthog` skill maps source paths to scene URLs.
