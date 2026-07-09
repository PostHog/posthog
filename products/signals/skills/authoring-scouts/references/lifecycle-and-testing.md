# Lifecycle, distribution, and testing

How scouts get discovered, scheduled, and dispatched; the two distribution paths and their exact mechanics; and how to test a scout in each.

## How a scout runs

- **Discovery.** The harness globs `signals-scout-*` over the project's skills (`LLMSkill` rows).
  Any matching skill is a scout.
  No registration step.
- **Config.** Each scout has one `SignalScoutConfig` per `(project, skill_name)` carrying `run_interval_minutes` (default 1440), `enabled`, `emit`, and a `last_run_at` stamp.
  A config is **auto-registered** the first time the coordinator sees a `signals-scout-*` skill without one — authoring the skill is enough to get a scout.
  To configure a fresh scout immediately (instead of waiting for the tick), register the config yourself with `posthog:signals-scout-config-create`, setting the schedule / emit posture in the same call; until one of those happens, the scout has no config row and won't show in `-config-list`.
  Config responses also carry the scout's `description`, read live from the skill's frontmatter — not a config field you set.
- **Coordinator.** A periodic Temporal workflow ticks (~every 30 min).
  Each tick it bounds candidates to projects enrolled via the `signals-scout` feature-flag allowlist, then dispatches every **enabled** scout whose schedule is **due** (`last_run_at is None`, or `now - last_run_at ≥ run_interval_minutes`), most-overdue first, capped per tick.
  There is no sampling — every due scout runs.
  `last_run_at` advances for everything dispatched.
- **Run.** Each dispatched scout becomes one sandboxed agent run with a short budget (single-digit minutes).
  The body is the system prompt; the agent orients, explores, files reports or remembers, and writes a one-paragraph summary to the run row.

Pausing a scout = `enabled=false`.
Slowing it = a larger `run_interval_minutes`.
Dry-running it = `emit=false`.
All three via `posthog:signals-scout-config-update` (get the `id` from `-config-list`), or set at creation time via `-config-create`.

## Path A — per-team (skills store)

The common path for a user customizing scouts for their own project.
A scout is just an `LLMSkill` row named `signals-scout-*`; create or edit it with the skills-store tools, and the harness globs it in on the next tick.

```text
# List existing scouts and other skills
posthog:skill-list {"search": "signals-scout"}

# Read a canonical scout to use as a template
posthog:skill-get {"skill_name": "signals-scout-error-tracking"}

# New scout from scratch — always include the report-channel allowed_tools
posthog:skill-create {"name": "signals-scout-<scope>", "description": "...", "body": "...", "allowed_tools": ["emit_report", "edit_report"], "compatibility": "...", "metadata": {"owner_team": "<team>", "scope": "<scope>"}}

# Register its config immediately with the schedule you want (otherwise the coordinator
# auto-registers the default every-24-hours schedule on its next tick)
posthog:signals-scout-config-create {"skill_name": "signals-scout-<scope>", "run_interval_minutes": 120}

# Adapt an existing per-team scout — use the SMALLEST primitive (find/replace, not full-body)
posthog:skill-get {"skill_name": "signals-scout-<scope>"}          # get current version first
posthog:skill-update {"skill_name": "signals-scout-<scope>", "base_version": N, "edits": [{"old": "...", "new": "..."}]}

# Duplicate a canonical scout into a new per-team scout you then edit (keeps the canonical intact)
posthog:skill-duplicate {"skill_name": "signals-scout-general", "new_name": "signals-scout-<scope>"}

# Bundle a reference file onto a per-team scout
posthog:skill-file-create {"skill_name": "signals-scout-<scope>", "path": "references/cookbook.md", "content": "...", "content_type": "text/markdown", "base_version": N}
```

Notes:

- Prefer `edits` (find/replace) over a full `body` rewrite for tweaks — a full rewrite forces you to reproduce the whole body and risks silently dropping unrelated content.
  Each `old` must match exactly once.
  Every write bumps an immutable `version`; chain further edits via `base_version`.
- **Divergence:** once you edit a canonical scout's row for your team, canonical sync treats it as **diverged** and stops force-updating it — you keep your edits but lose upstream improvements to that scout.
  To customize _without_ diverging, `duplicate` the canonical scout into a new `signals-scout-<your-scope>` row and edit that; leave the original alone.
- Writing reports needs the `signal_scout_report:write` scope, and the scratchpad needs `signal_scout_internal:write` (the sandbox has both).
  Authoring a scout doesn't require either — only the harness writes.

## Path B — canonical (in-repo, for PostHog contributors)

Improving a scout for **every** enrolled project.
Disk under `products/signals/skills/signals-scout-*/` is the source of truth; `lazy_seed` mirrors changes onto each enrolled team's `LLMSkill` rows on the next coordinator tick (or immediately via `python manage.py sync_signals_scout_skills --all-enabled`).
Teams that hand-edited a row are diverged and left alone.

```sh
hogli init:skill            # scaffold a new skill directory
hogli lint:skills           # validate frontmatter / syntax / binaries — fast, no Django
hogli build:skills          # render + package into dist/skills.zip
hogli sync:skill -- --name signals-scout-<scope>   # build + sync to .agents/skills/ for local agent testing
hogli unsync:skill -- --name signals-scout-<scope>
```

Authoring a new canonical scout is just creating `signals-scout-<scope>/SKILL.md` and merging — the next tick discovers it, seeds it onto enrolled teams, and auto-registers an enabled config on the default every-24-hours schedule.
**If you change the fleet shape (add/rename a scout, change the SKILL.md schema), update `products/signals/skills/AGENTS.md`.** On master, CI builds and publishes `dist/skills.zip` to the downstream distribution repos (the `ai-plugin` bundle and the standalone skills repo) automatically.

## Testing

**Dogfood the scout yourself first — before spending any real run.** The authoring agent has the same PostHog MCP tools a scout uses at runtime (`execute-sql`, `read-data-schema`, the per-product list tools, `signals-scout-project-profile-get`), so the cheapest iteration is to walk the scout's own logic against the live project by hand: confirm the watched entity exists and has the assumed shape, run the **discriminator** to check it separates signal from noise on this project's data, and run each **explore pattern**'s queries.
Free and instant — refine the body, re-run the queries, repeat, until the logic holds on real data.

Only once you're happy do you spend a real run.
`posthog:signals-scout-run-now {"id": <config_id>}` dispatches one run of the scout immediately, regardless of its schedule (get the `id` from `-config-list`) — the **initial real run**, the scout executing end-to-end in the harness.
The run is **asynchronous** — the call returns a workflow id right away; poll `-runs-list` / `-runs-retrieve` for the result.
A disabled scout can still be run this way (test before enabling), and a manual run doesn't touch the schedule or `last_run_at`.
It inherits the scheduled path's guards (403 not enabled, 429 over quota / daily run budget, 409 a run already in progress) and draws from the **same daily run budget** as scheduled runs — a dry-run (`emit=false`) counts too.
There's no free test run, and it's slow (async, one run per call): firing the same scout repeatedly in a short window burns the project's daily allowance (and can starve its scheduled scouts).
**Don't iterate via `-run-now`** — dogfood the queries by hand to get the body right, and reserve `-run-now` for the initial real run and the odd re-check after a genuinely meaningful change.
The loop is **dogfood → run once ready → inspect**:

1. Dogfood the discriminator + explore patterns yourself against the live project (above), refining the body until the logic holds — the cheap, iterable part.
2. Author the scout and register its config (`-config-create`, default `emit=true`), leaving `run_interval_minutes` at a sustainable value — no short-interval trick needed.
   Then spend one `-run-now` to watch the whole scout execute end-to-end, and inspect once it finishes:
   - `posthog:inbox-reports-list` — the reports it actually wrote.
   - `posthog:signals-scout-runs-list` — run summaries.
   - `posthog:signals-scout-runs-retrieve` — the full reasoning for one run.
   - `posthog:signals-scout-scratchpad-search` — the durable memory it wrote.
3. If it needs work, go back to dogfooding the queries by hand for the iteration, re-edit via `skill-update`, and spend another `-run-now` only once you've batched a meaningful change.

**Extra-careful variant — dry-run first.** For a scout you expect to be chatty, expensive, or high-stakes, set `emit=false` so it runs and logs what it _would_ have written (visible in `-runs-list` / `-runs-retrieve`) without writing to the inbox.
Trigger it with `-run-now`, inspect, refine, then `config-update` to `emit=true`.
For most scouts, writing straight away and watching the inbox is the faster calibration.

Repo contributors additionally get `hogli sync:skill` to run the scout against the local harness for a tighter loop before merging.
