# PosthogPluginService

Provides the PostHog plugin to agent sessions (Claude Code and Codex). The plugin is a directory containing `plugin.json` and a `skills/` folder of markdown instruction files that teach agents how to use PostHog APIs.

`AgentService` calls `getPluginPath()` when starting each session to get the path to the assembled plugin directory.

## Skills

Skills are the main content of the plugin. Each skill is a directory containing a `SKILL.md` and optional `references/` folder with supporting docs. For example, the `query-data` skill teaches agents how to write HogQL queries against PostHog's API.

Skills are published independently from the desktop app at a stable GitHub releases URL (`skills.zip`). This service ensures agents always have the latest skills without requiring an app update.

### Skill Sources

The plugin directory is assembled from three skill sources, merged in priority order (later overrides earlier for same-named skills):

| Source | Location | When used |
|---|---|---|
| **Shipped** | `plugins/posthog/skills/` | Always — committed to the repo |
| **Remote** | GitHub releases `skills.zip` | Downloaded at build time and every 30 min at runtime |
| **Local dev** | `plugins/posthog/local-skills/` | Dev mode only — gitignored |

A "skill name" is its directory name. If remote and shipped both have `query-data/`, the remote version wins. If local-dev also has `query-data/`, that wins over both.

## Build Time

`copyPosthogPlugin()` in `vite-main-plugins.mts` assembles the plugin during `writeBundle`:

1. Copies allowed plugin entries into `.vite/build/plugins/posthog/`
2. Downloads `skills.zip` via `curl`, extracts with `unzip`, overlays into the build output
3. In dev mode only: overlays `plugins/posthog/local-skills/` on top
4. Download failure is non-fatal — build continues with shipped skills only

Vite watches `plugins/posthog/` (and `local-skills/` in dev) for hot-reload.

## Runtime

`PosthogPluginService` is an InversifyJS singleton that keeps the plugin fresh in production builds where the Vite dev server isn't running.

**On startup:**
1. Creates `{userData}/plugins/posthog/` (the runtime plugin dir)
2. Assembles it: copies `plugin.json` from bundled, merges bundled skills + any previously-downloaded remote skills
3. One-time: cleans up skills earlier builds copied into `$HOME/.agents/skills/` (see below)
4. Starts a 30-minute interval timer
5. Kicks off the first async download

**Every 30 minutes (`updateSkills`):**
1. Downloads `skills.zip` using `net.fetch` (Electron's network stack, respects proxy)
2. Extracts to a temp dir via `unzip`
3. Atomically swaps into `{userData}/skills/`
4. Re-assembles the runtime plugin dir
5. On failure: logs a warning, keeps existing skills, retries next interval

**`getPluginPath()`** — called by `AgentService` when starting sessions:
- Dev mode → bundled path (Vite already merged everything)
- Prod → `{userData}/plugins/posthog/` (with downloaded updates)
- Fallback → bundled path

### Cross-harness skills (no global writes)

`$HOME/.agents/skills/` is a shared, cross-agent skills directory that other tools (e.g. standalone Codex) also read. The app **never writes skills there.** It only reads it, to surface the user's own Codex skills in the Skills tab. The "use your skills in any harness" merge happens per-session, scoped to the process the app spawns:

- **Claude sessions** load the user's Codex skills (`$HOME/.agents/skills`) as an extra synthetic plugin — see `discover-plugins.ts` (`discoverCodexSkills`), deduped against the bundled catalog and `$HOME/.claude/skills`.
- **Codex sessions** get a private `CODEX_HOME` (`{userData}/codex-home`) whose `skills/` holds the bundled catalog + the user's `$HOME/.claude/skills` — see `codex-home.ts` (`prepareCodexHome`). codex-acp scans `$CODEX_HOME/skills` plus `$HOME/.agents/skills`, so the user's own Codex skills still load while ours stay app-private.

**One-time cleanup.** Earlier builds copied skills into the shared `$HOME/.agents/skills/` (the bundled catalog via `syncCodexSkills`, and the user's skills via an automatic mirror). `cleanupLegacyCodexMirror` (in `codex-mirror.ts`) removes those leftovers once per install so the directory becomes the user's own again. It only deletes skills it can prove we wrote: names tracked in `.posthog-mirror.json`, and bundled-catalog copies whose `SKILL.md` is byte-identical to ours (so a user's own same-named skill is never deleted).

## Dev Workflow

### Testing with local skills

1. Create a skill directory in `plugins/posthog/local-skills/`, e.g.:
   ```
   plugins/posthog/local-skills/my-skill/SKILL.md
   ```
2. Run `pnpm dev:code` — Vite watches and hot-reloads
3. The local skill overrides any shipped or remote skill with the same name

### Pulling remote skills locally for editing

```sh
pnpm pull-skills
```

Downloads the latest `skills.zip` into `plugins/posthog/local-skills/`. You can then edit them locally and Vite will pick up changes.
