# Skill — editing agents safely

The full edit-promote loop. Load this whenever the user wants to
change any part of an existing agent — system prompt, skill, tool,
limit, model, anything.

## The non-negotiable order

```text
1. inspect       — know what you're editing
2. branch draft  — never mutate live or ready
3. edit          — surgical, file-by-file
4. validate      — catch structural breaks before freeze
5. freeze        — draft → ready, stamps sha256
6. test          — run scripted cases against the ready revision
7. promote       — ready → live, with explicit user consent
8. observe       — first real session(s) after promote, verify
```

Skipping a step is the most common cause of regressions. Don't
skip — even small edits.

## Step 1 — inspect (always)

Read the live revision first, even if the user says "just change
X". You need to know:

- What revision is currently live
- What other things in the spec / bundle might be affected
- Whether there are pending approvals or in-flight sessions you'd
  disrupt

Use the standard flow from `skills/reading-an-agent`. Don't
proceed until you've read both `spec` and the relevant file(s).

## Step 2 — branch a draft

Always: `agent-applications-revisions-new-draft-create` from the
current `live_revision_id`. You get a fresh draft pre-populated
with the live bundle + spec.

NOT this:

- ❌ Edit a `ready` revision directly. They're frozen — every
  call will fail.
- ❌ Create an empty draft and rebuild. You'll drift from live.
- ❌ Branch from an archived revision. You'd be regressing.

In the console, `@posthog/ui/focus` to the new draft so the user
sees it.

## Step 3 — edit

Choose the right verb:

| Verb                                           | When                                                   | Reversibility                              |
| ---------------------------------------------- | ------------------------------------------------------ | ------------------------------------------ |
| `agent-applications-revisions-partial-update`  | Change `spec` (model, limits, triggers, tools[], etc.) | Easy — the next partial-update overwrites  |
| `agent-applications-revisions-agent-md-update` | Overwrite `agent.md` (the system prompt)               | Easy — re-write                            |
| `agent-applications-revisions-skills-update`   | Upsert one skill (body + companion files)              | Easy — re-write                            |
| `agent-applications-revisions-skills-destroy`  | Delete one skill                                       | **Hard** — content gone unless you have it |
| `agent-applications-revisions-tools-update`    | Upsert one custom tool (source + schema)               | Easy — re-write                            |
| `agent-applications-revisions-tools-destroy`   | Delete one custom tool                                 | **Hard** — content gone unless you have it |

These are all native `@posthog/agent-applications-*` tools — there's
no bulk bundle-replace verb, which is deliberate: edit the one thing
that changed (`agent-md-update` / `skills-update` / `tools-update`)
rather than rewriting the whole bundle.

For each edit, surface to the user:

- What file changed
- A one-line summary of the change
- The before/after diff if it's small (< 20 lines), else just the
  summary

In the console, `@posthog/ui/focus` to each file as you touch it.

## Step 4 — validate

`agent-applications-revisions-validate-create` against the draft.
Returns `{ ok, errors[], warnings[] }`.

- **Errors block freeze.** Fix every one before proceeding.
- **Warnings don't block.** Read them; if they're about your
  change, address. If they're pre-existing (skills declared but
  unused before your edit), leave them alone — not your scope.

Common errors:

- `unknown_tool_id` — you wrote `@posthog/queries` instead of
  `@posthog/query`. Cross-check against `agent-native-tools-list`.
- `unresolved_skill_path` — `spec.skills[].path` points at a file
  that isn't in the bundle. Either add the file or remove the spec
  entry.
- `missing_secret` — `spec.secrets[]` lists a name without a
  corresponding env value. Load `skills/secrets-and-integrations`.
- `invalid_spec` — Zod parse failed. The error message names the
  field; fix it.

## Step 5 — freeze

`agent-applications-revisions-freeze-create`. State flips
`draft → ready`, `bundle_sha256` is stamped, no more edits.

**Confirm with the user before freezing** if any of these are
true:

- The edit touches `spec.triggers[]` (changes the agent's input
  surface)
- The edit touches `spec.tools[]` in a way that adds a new tool
  (more capability)
- The edit removes a skill or file referenced in `agent.md`

For a single-file `agent.md` edit, you can freeze without
re-confirmation — but still announce ("Freezing revision r_new123
now.") so the user knows the state changed.

## Step 6 — test

Load `skills/running-and-evaluating-tests`. At minimum:

- Find `bundle/tests/*.json` (if any). Run them all.
- If there are no tests, write one for the case the edit targets,
  then run it.
- For non-trivial edits, run a real-inference test (a separate
  test type, more expensive — confirm cost with the user first).

If tests fail, you cannot edit the ready revision. Branch a new
draft from the just-frozen ready, fix, re-freeze, re-test. Yes,
this is more work than mutating ready — that friction is the
point. Frozen means frozen.

## Step 7 — promote

**Confirm with the user before promoting**, every time:

> Ready to promote r_new123 to live? This will:
>
> - Make r_new123 the active revision for all triggers
> - Auto-archive r_xyz789 (currently live)
> - In-flight sessions on r_xyz789 will finish; new triggers hit r_new123
>
> Reply 'promote' to proceed, or tell me to do something else first.

Wait for the user's confirmation token. Don't paraphrase ("ok,
ship it!") into a promote — be literal.

Then call `agent-applications-revisions-promote-create`.

## Step 8 — observe

After promoting, **watch the first real session(s)**. In the
console, `@posthog/ui/focus` to `@posthog/agent-applications-sessions-list`
and tell the user you're watching for the next fire. If something
looks wrong in the first 1-3 sessions, you have a quick rollback:

## Rollback

Promote the previous revision back to live:

`agent-applications-revisions-promote-create` against the
previously-live revision (which is now in `archived` state, but
re-promotable).

Confirm with the user before rolling back — same shape as a
promote confirmation.

For a catastrophic bug, you can also disable the trigger
temporarily by editing the spec to remove the trigger and
promoting THAT — but that requires the whole draft-freeze-promote
cycle. Direct re-promote of the old revision is faster.

## When the user wants to skip steps

Common asks:

- **"just edit the prompt, don't bother with a test"** —
  Acknowledge that the small edit is low-risk, but still validate
  - freeze + promote. Skip the test if the user explicitly waives
    it AND the edit is purely cosmetic (typo, formatting). Anything
    semantic still gets a test.
- **"don't ask me to confirm promote, just do it"** — Refuse.
  See `skills/safety-and-boundaries` rule #3. Promote is a
  production-affecting write; the user has to type the word.
- **"I'll edit it later, just leave the draft"** — Fine.
  Drafts persist; the user can resume by calling you again with
  the draft revision id. Surface the id explicitly so they can
  find it.

## What goes wrong if you skip steps

- **Skip inspect:** edit conflicts with something else in the
  spec / bundle the user forgot about. Fix takes a second
  revision.
- **Skip validate:** runtime fails at session start with an
  ugly error. User loses trust.
- **Skip test:** first real session triggers the regression
  the test would have caught. Real users / Slack channels /
  alert systems see the bad output. Rollback is fast but the
  noise is already out.
- **Skip confirm-promote:** the user wakes up to "wait what's
  live?". This is the single biggest trust-breaker for the
  concierge — DO NOT skip.
