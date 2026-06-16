# Skills: zip export + Claude Code plugin marketplace

Spec-compliant ([agentskills.io](https://agentskills.io/specification)) packaging for stored
skills, plus a live, team-private Claude Code plugin marketplace served straight from the
database — no git repo, no static files, no build step. Modeled on Mnemion's approach
(synthesize a virtual git repo on every request).

## Layout

| Module | Django? | Responsibility |
| --- | --- | --- |
| `packaging.py` | no | `SKILL.md` frontmatter serialization, zip + marketplace file-tree assembly |
| `git_smart_http.py` | no | read-only Git Smart HTTP v2: file tree → packfile / ref advertisement |
| `adapters.py` | yes | the only ORM layer: `LLMSkill` rows → the plain export dataclasses |
| `auth.py` | yes | HTTP Basic → Project Secret API Key bridge for `git clone` |
| `../api/marketplace_views.py` | yes | the two git endpoints (`info/refs`, `git-upload-pack`) |

The two stdlib-only modules are deliberately Django-free so the packfile synthesis is
unit-testable against the real `git` binary without booting the app
(`api/test/test_marketplace_git.py`, `api/test/test_marketplace_packaging.py`).

## Endpoints

- **Zip** — `GET /api/projects/:team/llm_skills/name/:name/export` → `application/zip`, one
  spec-compliant skill directory nested under `:name/` (web-authenticated, `llm_skill:read`).
- **Marketplace** — `…/llm_skills/marketplace.git/info/refs` + `…/git-upload-pack`. The repo
  root is `…/llm_skills/marketplace.git`; `git` appends the rest. One plugin per team
  (`posthog-skills`).

## Spec mapping (storage → SKILL.md)

- `allowed_tools` (stored list) → `allowed-tools` (spec's hyphenated, space-separated string)
- platform `version` → `metadata.version` (the spec defines no top-level version field)
- `description` is validated against the spec's 1024 limit on export (`validate_for_export`)

## Auth: a dedicated, revocable marketplace credential (not a personal API key)

`git clone` (and therefore `/plugin marketplace add`) speaks only HTTP Basic via git
credential helpers — never Bearer, never OAuth. So the marketplace uses a **Project Secret
API Key** (`phs_…`): a project-scoped, user-less, independently revocable service credential,
carried as the Basic password. `auth.py` bridges Basic → PSAK; `APIScopePermission` then
enforces the `llm_skill:read` scope, `psak_allowed_actions`, and team binding
(`key.team == view.team`). The credential lives in the user's OS keychain / git credential
store, not in Claude Code's plaintext config.

## Versioning / auto-update

Claude Code re-pulls when the `version` in `marketplace.json` / `plugin.json` changes. We
derive it from team content (`compute_plugin_version` keyed on the latest skill change time)
so any publish bumps it forward monotonically with zero manual semver.

> **Open question (the spike answers it):** whether Claude Code re-pulls on any version
> *difference* or only strictly-greater, and whether background auto-update reliably re-auths
> via the credential helper. The monotonic-timestamp scheme is safe for either.

## Job one — testing auto-updates (run once a dev env is reachable by a real Claude Code)

1. Expose the dev stack at a URL Claude Code can reach (devbox public URL or a `cloudflared`
   tunnel in front of `./bin/start` — `localhost` won't do).
2. Mint the credential:
   `POST /api/environments/:team/project_secret_api_keys` with `{"label": "claude-code", "scopes": ["llm_skill:read"]}`
   (or the project settings UI). Copy the `phs_…` value (shown once).
3. Create a skill (UI, API, or the `skill-create` MCP tool) so the marketplace is non-empty.
4. In Claude Code:
   `/plugin marketplace add https://token:phs_…@<host>/api/projects/:team/llm_skills/marketplace.git`
   then install the `posthog-skills` plugin and confirm a skill loads (`/posthog-skills:<name>`).
5. Publish a change to that skill → the plugin version advances. Trigger / wait for Claude
   Code's marketplace update and confirm the new `SKILL.md` content is pulled.
6. Record what actually triggers the re-pull (version diff vs. strictly-greater; manual update
   vs. background) and whether the credential helper re-auths unattended — that resolves the
   open question above and tells us whether the version scheme needs adjusting.

Rung 1 (protocol correctness — clone, shallow clone, version bump, `git fsck`) is already
proven offline against the real `git` binary in `test_marketplace_git.py`; rung 2 (the steps
above) is the only part that needs a live client.
