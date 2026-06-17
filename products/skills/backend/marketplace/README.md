# Skills: zip export + Claude Code plugin marketplace

Spec-compliant ([agentskills.io](https://agentskills.io/specification)) packaging for stored
skills, plus a live, team-private Claude Code plugin marketplace served straight from the
database — no git repo, no static files, no build step. Modeled on Mnemion's approach
(synthesize a virtual git repo on every request).

## Layout

| Module                        | Django? | Responsibility                                                             |
| ----------------------------- | ------- | -------------------------------------------------------------------------- |
| `packaging.py`                | no      | `SKILL.md` frontmatter serialization, zip + marketplace file-tree assembly |
| `git_smart_http.py`           | no      | read-only Git Smart HTTP v2: file tree → packfile / ref advertisement      |
| `adapters.py`                 | yes     | the only ORM layer: `LLMSkill` rows → the plain export dataclasses         |
| `credentials.py`              | yes     | mint / reuse / rotate the per-user read-only marketplace credential        |
| `auth.py`                     | yes     | HTTP Basic → Project Secret API Key bridge for `git clone`                 |
| `../api/marketplace_views.py` | yes     | the two git endpoints (`info/refs`, `git-upload-pack`)                     |

The two stdlib-only modules are deliberately Django-free so the packfile synthesis is
unit-testable against the real `git` binary without booting the app
(`api/test/test_marketplace_git.py`, `api/test/test_marketplace_packaging.py`).

## Endpoints

- **Zip export** — `GET /api/projects/:team/llm_skills/name/:name/export` → `application/zip`,
  one spec-compliant skill directory nested under `:name/` (web-authenticated, `llm_skill:read`).
- **Zip import** — `POST /api/projects/:team/llm_skills/import` (multipart `file` field, a spec
  skill `.zip`) → creates the skill (web-authenticated, `llm_skill:write`). The inverse of
  export: `parse_skill_zip` reads `SKILL.md` frontmatter + bundled files. Round-trips with export.
- **Install command** — `GET` (read connection state, no mint) + `POST` (mint/rotate the
  credential, returns the ready-to-paste command) `…/llm_skills/marketplace/install-command`.
  Web-authenticated; GET needs `llm_skill:read`, POST needs `llm_skill:write`. Powers the
  "Connect to Claude Code" UI and the `skill-store-install-command` MCP tool. See
  [Auth](#auth-a-dedicated-revocable-marketplace-credential-not-a-personal-api-key) for the
  per-user credential model.
- **Marketplace** — `…/llm_skills/marketplace.git/info/refs` + `…/git-upload-pack`. The repo
  root is `…/llm_skills/marketplace.git`; `git` appends the rest. One plugin per team
  (`posthog-skill-store`).

## Spec mapping (storage → SKILL.md)

- `allowed_tools` (stored list) → `allowed-tools` (spec's hyphenated, space-separated string)
- platform `version` → `metadata.version` (the spec defines no top-level version field)
- `description` is validated against the spec's 1024 limit on export (`validate_for_export`)

## Cross-agent portability

The `SKILL.md` artifact is the open standard ([agentskills.io](https://agentskills.io/specification)),
read by Claude Code, OpenAI Codex, Gemini CLI, Copilot/VS Code, Cursor, Windsurf, and more — so the
zip export drops straight into any of them. Each skill tree also includes an `agents/openai.yaml`
sidecar (`render_codex_openai_yaml`) carrying Codex UI metadata; every other agent ignores it. On
import (`parse_skill_zip`) that sidecar is skipped since export regenerates it.

## Auth: a dedicated, revocable marketplace credential (not a personal API key)

`git clone` (and therefore `/plugin marketplace add`) speaks only HTTP Basic via git
credential helpers — never Bearer, never OAuth. So the marketplace uses a **Project Secret
API Key** (`phs_…`): a project-scoped, independently revocable service credential, carried as
the Basic password. `auth.py` bridges Basic → PSAK; `APIScopePermission` then enforces the
`llm_skill:read` scope, `psak_allowed_actions`, and team binding (`key.team == view.team`).

**One credential per user, not per team** (`credentials.py`). The key is labeled
`Skill store · <user-id>` and scoped read-only (`llm_skill:read`), so a leaked credential can
only read this team's skills. Per-user keying is the important part: the raw token is
unrecoverable after creation, so "reuse" can only mean create-if-absent / roll-if-present —
and rolling issues a fresh token that invalidates the old one. If that key were shared
team-wide, every new teammate connecting Claude Code would roll it and break everyone else's
working install. Keying it per user means a roll only ever invalidates the roller's own setup;
nobody else is touched. `install-command`'s `GET` reports whether you're already connected
without minting (the token can't be shown again), and `POST` only rolls when `rotate=true`, so
just glancing at the modal never breaks a working setup. The minted token lives in the user's
OS keychain / git credential store.

## Versioning / auto-update

Claude Code re-pulls when the `version` in `marketplace.json` / `plugin.json` changes. We
derive it from team content (`compute_plugin_version` keyed on the latest skill change time, in
milliseconds) so any publish/archive bumps it forward monotonically with zero manual semver.
The synthesized repo is cached on `team_id` + that version, so repeated clones and auto-update
polls reuse one synthesis and the cache invalidates automatically on any change.

> **Open question (the spike answers it):** whether Claude Code re-pulls on any version
> _difference_ or only strictly-greater, and whether background auto-update reliably re-auths
> via the credential helper. The monotonic-timestamp scheme is safe for either.

## Job one — testing auto-updates (run once a dev env is reachable by a real Claude Code)

1. Expose the dev stack at a URL Claude Code can reach (devbox public URL or a `cloudflared`
   tunnel in front of `./bin/start` — `localhost` won't do).
2. Get the ready-to-paste command (mints the per-user read-only credential and embeds it):
   the **Connect to Claude Code** button in the skills UI, `POST
/api/environments/:team/llm_skills/marketplace/install-command`, or the
   `skill-store-install-command` MCP tool. The `phs_…` token is shown once.
3. Create a skill (UI, API, or the `skill-create` MCP tool) so the marketplace is non-empty.
4. In Claude Code, paste the command (it is the full
   `/plugin marketplace add https://x-access-token:phs_…@<host>/api/projects/:team/llm_skills/marketplace.git`),
   then install the `posthog-skill-store` plugin and confirm a skill loads (`/posthog-skill-store:<name>`).
5. Publish a change to that skill → the plugin version advances. Trigger / wait for Claude
   Code's marketplace update and confirm the new `SKILL.md` content is pulled.
6. Record what actually triggers the re-pull (version diff vs. strictly-greater; manual update
   vs. background) and whether the credential helper re-auths unattended — that resolves the
   open question above and tells us whether the version scheme needs adjusting.

Rung 1 (protocol correctness — clone, shallow clone, version bump, `git fsck`) is already
proven offline against the real `git` binary in `test_marketplace_git.py`; rung 2 (the steps
above) is the only part that needs a live client.
