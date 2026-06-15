# Lifecycle, distribution, and testing

How scouts get discovered, scheduled, and dispatched; the two distribution paths and their
exact mechanics; and how to test a scout in each.

## How a scout runs

- **Discovery.** The harness globs `signals-scout-*` over the project's skills (`LLMSkill`
  rows). Any matching skill is a scout. No registration step.
- **Config.** Each scout has one `SignalScoutConfig` per `(project, skill_name)` carrying
  `run_interval_minutes` (default 60), `enabled`, `emit`, and a `last_run_at` stamp. A
  config is **auto-registered** the first time the coordinator sees a `signals-scout-*`
  skill without one — authoring the skill is enough to get a scout. To configure a fresh
  scout immediately (instead of waiting for the tick), register the config yourself with
  `posthog:signals-scout-config-create`, setting the schedule / emit posture in the same
  call; until one of those happens, the scout has no config row and won't show in
  `-config-list`. Config responses also carry the scout's `description`, read live from the
  skill's frontmatter — not a config field you set.
- **Coordinator.** A periodic Temporal workflow ticks (~every 30 min). Each tick it bounds
  candidates to projects enrolled via the `signals-scout` feature-flag allowlist, then
  dispatches every **enabled** scout whose schedule is **due** (`last_run_at is None`, or
  `now - last_run_at ≥ run_interval_minutes`), most-overdue first, capped per tick. There is
  no sampling — every due scout runs. `last_run_at` advances for everything dispatched.
- **Run.** Each dispatched scout becomes one sandboxed agent run with a short budget
  (single-digit minutes). The body is the system prompt; the agent orients, explores, emits
  or remembers, and writes a one-paragraph summary to the run row.

Pausing a scout = `enabled=false`. Slowing it = a larger `run_interval_minutes`. Dry-running
it = `emit=false`. All three via `posthog:signals-scout-config-update` (get the `id` from
`-config-list`), or set at creation time via `-config-create`.

## Path A — per-team (skills store)

The common path for a user customizing scouts for their own project. A scout is just an
`LLMSkill` row named `signals-scout-*`; create or edit it with the skills-store tools, and
the harness globs it in on the next tick.

```text
# List existing scouts and other skills
posthog:llma-skill-list {"search": "signals-scout"}

# Read a canonical scout to use as a template
posthog:llma-skill-get {"skill_name": "signals-scout-error-tracking"}

# New scout from scratch
posthog:llma-skill-create {"name": "signals-scout-<scope>", "description": "...", "body": "...", "compatibility": "...", "metadata": {"owner_team": "<team>", "scope": "<scope>"}}

# Register its config immediately with the schedule you want (otherwise the coordinator
# auto-registers an hourly default on its next tick)
posthog:signals-scout-config-create {"skill_name": "signals-scout-<scope>", "run_interval_minutes": 120}

# Adapt an existing per-team scout — use the SMALLEST primitive (find/replace, not full-body)
posthog:llma-skill-get {"skill_name": "signals-scout-<scope>"}          # get current version first
posthog:llma-skill-update {"skill_name": "signals-scout-<scope>", "base_version": N, "edits": [{"old": "...", "new": "..."}]}

# Duplicate a canonical scout into a new per-team scout you then edit (keeps the canonical intact)
posthog:llma-skill-duplicate {"skill_name": "signals-scout-general", "new_name": "signals-scout-<scope>"}

# Bundle a reference file onto a per-team scout
posthog:llma-skill-file-create {"skill_name": "signals-scout-<scope>", "path": "references/cookbook.md", "content": "...", "content_type": "text/markdown", "base_version": N}
```

Notes:

- Prefer `edits` (find/replace) over a full `body` rewrite for tweaks — a full rewrite
  forces you to reproduce the whole body and risks silently dropping unrelated content. Each
  `old` must match exactly once. Every write bumps an immutable `version`; chain further
  edits via `base_version`.
- **Divergence:** once you edit a canonical scout's row for your team, canonical sync treats
  it as **diverged** and stops force-updating it — you keep your edits but lose upstream
  improvements to that scout. To customize _without_ diverging, `duplicate` the canonical
  scout into a new `signals-scout-<your-scope>` row and edit that; leave the original alone.
- Emitting needs the `signal_scout_internal:write` scope (the sandbox has it). Authoring a
  scout doesn't require it — only the harness emits.

## Path B — canonical (in-repo, for PostHog contributors)

Improving a scout for **every** enrolled project. Disk under
`products/signals/skills/signals-scout-*/` is the source of truth; `lazy_seed` mirrors
changes onto each enrolled team's `LLMSkill` rows on the next coordinator tick (or
immediately via `python manage.py sync_signals_scout_skills --all-enabled`). Teams that
hand-edited a row are diverged and left alone.

```sh
hogli init:skill            # scaffold a new skill directory
hogli lint:skills           # validate frontmatter / syntax / binaries — fast, no Django
hogli build:skills          # render + package into dist/skills.zip
hogli sync:skill -- --name signals-scout-<scope>   # build + sync to .agents/skills/ for local agent testing
hogli unsync:skill -- --name signals-scout-<scope>
```

Authoring a new canonical scout is just creating `signals-scout-<scope>/SKILL.md` and
merging — the next tick discovers it, seeds it onto enrolled teams, and auto-registers an
enabled hourly config. **If you change the fleet shape (add/rename a scout, change the
SKILL.md schema), update `products/signals/skills/AGENTS.md`.** On master, CI builds and
publishes `dist/skills.zip` to the downstream distribution repos (the `ai-plugin` bundle and
the standalone skills repo) automatically.

## Testing

You can't trigger a synchronous run as a user — scouts fire on their schedule. The standard
loop is **emit + inspect**: ship the scout live (`emit=true` is the default), let it emit,
and calibrate against what actually lands.

1. Ship with the default `emit=true` and a short `run_interval_minutes` (e.g. 10) so it
   fires soon — set both at creation via `posthog:signals-scout-config-create`.
2. After a tick, inspect:
   - `posthog:inbox-reports-list` — the findings it actually emitted.
   - `posthog:signals-scout-runs-list` — run summaries.
   - `posthog:signals-scout-runs-retrieve` — the full reasoning for one run.
   - `posthog:signals-scout-scratchpad-search` — the durable memory it wrote.
3. Refine the body for whatever it false-positived or missed — tighten the discriminator,
   add disqualifiers, fix emit calibration. Re-edit via `llma-skill-update`.
4. Once it's landing the right findings, `config-update` to restore a sustainable interval
   (hourly or slower).

**Extra-careful variant — dry-run first.** For a scout you expect to be chatty, expensive,
or high-stakes, set `emit=false` so it runs and logs what it _would_ have emitted (visible in
`-runs-list` / `-runs-retrieve`) without writing to the inbox. Inspect, refine, then
`config-update` to `emit=true`. For most scouts, emitting straight away and watching the
inbox is the faster calibration.

Repo contributors additionally get `hogli sync:skill` to run the scout against the local
harness for a tighter loop before merging.
