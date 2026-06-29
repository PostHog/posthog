# Skill — authoring new agents

How to build a deployable agent from scratch. Load this only when
the user is creating a NEW agent. For editing existing agents,
use the `editing-agents-safely` playbook instead.

## Don't author until you know the brief

Before any MCP call, get answers to:

1. **What does this agent do?** One sentence. If you can't write
   the sentence yet, the user can't either — ask more questions.
2. **What triggers it?** Cron? Slack mentions? Chat from
   PostHog Code? A webhook from an external system?
3. **What does it have access to?** PostHog data? Slack? An
   external service via a custom tool or MCP?
4. **What's the success criterion?** One concrete example of a
   trigger and the desired response.

Refuse to build until you have all four. "Sure, let me design
something" without the brief produces 60 minutes of work the user
will throw away.

## The phases

```text
1. discover     — what's available, what already exists
2. design       — write the spec
3. create       — application + empty draft
4. configure    — wire secrets (punch-out)
5. write        — agent.md, skills, custom tools
6. validate     — structural check
7. freeze + test — sandboxed runs, self-eval
8. promote      — live, with explicit consent
```

## Phase 1 — discover

```text
posthog__agent-resolve-resource               → read this playbook before you design
posthog__agent-native-tools-list              → built-in tool catalog (valid native tool ids)
posthog__agent-applications-list              → existing agents (clone target?)
```

If the user describes something close to an existing agent,
**suggest cloning** instead of writing fresh. Use
`posthog__agent-applications-revisions-clone-from-create` to start from
that bundle. Saves a lot of work.

For platform-level templates (skill templates, custom-tool
templates) — these are designed but not yet shipped. Don't
reference them until they exist.

## Phase 2 — design the spec

Re-read this `authoring-new-agents` playbook via
`posthog__agent-resolve-resource` before you design — it's the
reference for every field below. Decide the _values_ here; let the
playbook settle the _structure_, and pin down valid native tool ids
with `posthog__agent-native-tools-list`.

Sketch the spec in your head / out loud with the user, BEFORE
calling any create endpoint. Cover:

- **`models`** — leave it at the default (`auto` / `medium`) unless the
  user has a preference; don't hardcode a model id. Load
  `skills/choosing-the-model` to match the policy to the job.
- **`triggers`** — one is fine; many is fine; pick what the user
  asked for. Each trigger has its own config.
- **`tools[]`** — minimum needed for the job. Don't pre-emptively
  add tools the agent might want — that's how prompts get
  confused. Add later if needed.
- **`mcps[]`** — leave empty unless the user named a specific
  external MCP server.
- **`skills[]`** — usually 0-3 for v0. Plan one per "domain of
  knowledge"; don't pre-create skills for ideas the agent might
  reach for.
- **`secrets[]`** — list any per-application keys the agent's tools
  read (e.g. `"STRIPE_API_KEY"`). Trigger-required keys are handled
  separately — see the note after this list.
- **`limits`** — usually defaults are fine. Tighten if the user
  needs a hard cost cap.
- **`auth`** — for chat/mcp triggers, almost always `posthog` or
  `posthog_internal`; webhook usually `shared_secret`. `public` is
  unsafe unless the agent is genuinely B2C.
- **`reasoning`** — start unset (provider default). Bump to
  `medium` if the agent reasons hard; `high` if it does long
  triage; rarely `xhigh`.

Show the proposed spec to the user before creating. They will
catch things you missed.

### Get the shape from the tools, not from memory

Don't guess the `spec` structure from memory or hand-copy it from
another agent — guessing the shape is what used to cost 5-10
trial-and-error turns per session. Instead: read this
`authoring-new-agents` playbook via `posthog__agent-resolve-resource`
for the field reference (every field, enum, default, and the
discriminated unions for `triggers[]` with per-trigger auth, `tools[]`
as `native` vs `custom` vs `client`, and `secrets[]` as bare string vs
`{name, allowed_hosts}`); pin down valid native tool ids with
`posthog__agent-native-tools-list` (the validator rejects unknown ones);
and run `posthog__agent-applications-revisions-validate-create` on a
draft spec to surface concrete errors rather than guessing whether the
shape is right.

Two facts the field reference can't give you, because they aren't
part of the spec:

- **Trigger-required secrets** (`SLACK_SIGNING_SECRET`,
  `SLACK_BOT_TOKEN` for `slack` triggers) are NOT listed in
  `spec.secrets[]`. They come from the platform-wide
  `TRIGGER_REQUIRED_SECRETS` registry and live in `encrypted_env`;
  the promote endpoint refuses if they're missing. See
  the `secrets-and-integrations` playbook.
- **Custom-tool `source.ts` shape** (Phase 5) is the tool's runtime
  contract, not spec structure — the field reference won't describe it.

## Phase 3 — create

```text
posthog__agent-applications-create           → returns { id, slug }
posthog__agent-applications-revisions-create → empty draft revision (with spec)
```

`revisions-create` accepts the full spec inline — pass the Phase 2
JSON straight in. Don't create-empty-then-partial-update; that's
two round-trips for nothing.

**Drive the PostHog Code UI** so the user follows along. Right after
`posthog__agent-applications-create` returns, call:

```text
focus_tab({ slug: "<new-slug>", tab: "configuration" })
```

so the user's panel switches to the new agent's configuration view
before you start writing files. Then after each significant write
(spec patched, agent.md written, a custom tool added), call the
matching `focus_*`:

- `focus_revision({ slug, revisionId })` after `revisions-create` /
  `new-draft-create`
- `focus_file({ slug, path })` after `file-update`
- `focus_spec_section({ slug, section })` when discussing a spec
  section the user can't see

`slug` is ALWAYS required on every `focus_*` call — never infer
from the user's current page (they navigate while you think).

If you need to amend the spec on a draft:

```text
posthog__agent-applications-revisions-partial-update revision_id=<rid> spec=<json>
```

## Phase 4 — configure secrets

For each item in `spec.secrets[]`, you cannot accept the value
directly. Load the `secrets-and-integrations` playbook and follow the
punch-out flow.

**Also check trigger-required secrets** — some trigger types demand
entries in `encrypted_env` that the spec doesn't name explicitly
(`SLACK_SIGNING_SECRET` for `slack` triggers, today). The promote
endpoint refuses if any are missing; catch them here so the user
isn't surprised at the end. See the `secrets-and-integrations` playbook
→ "Trigger-required secrets" for the registry + punch-out flow.

When the new agent must call PostHog or a third-party API as the
user, load the `authenticating-as-the-user` playbook to wire its identity
provider + scopes.

## Phase 5 — write the bundle (typed authoring API)

The authoring surface is **typed resources, not file paths**. You
never write a path; you upsert a typed object via one of these calls:

| Resource       | Tool                                                      | Body shape                                             |
| -------------- | --------------------------------------------------------- | ------------------------------------------------------ |
| System prompt  | `posthog__agent-applications-revisions-agent-md-update`   | `{ content }`                                          |
| Spec           | `posthog__agent-applications-revisions-partial-update`    | `{ spec }` (author-facing slice — no skills/tools)     |
| Author a skill | `posthog__llm-skills-create`                              | `{ name, description, body, files? }` (in the store)   |
| Find skills    | `posthog__llm-skills-search`                              | `{ search? }`                                          |
| Pin skills     | `posthog__agent-applications-revisions-skill-refs-update` | `{ skill_refs: [{ from_template, alias, version? }] }` |
| One tool       | `posthog__agent-applications-revisions-tools-update`      | `{ description, args_schema, source }`                 |
| Delete tool    | `posthog__agent-applications-revisions-tools-destroy`     | (no body)                                              |

**`spec.skills[]` and `spec.tools[]` are server-derived at freeze.**
You can't write them via `partial-update`. The janitor scans the typed
resources in the bundle and emits the spec entries automatically.
Orphan skills, dangling tool refs, and renaming-without-spec-patch
are structurally impossible.

Start with `agent.md` — the system prompt. Keep it tight:

- Identity ("you are X")
- The job ("for each Y, do Z")
- The hard rules (3-5, max)
- Tone

If the agent has > 1 distinct chunk of "how to do the job" (say,
both "how to triage an alert" AND "how to format a Slack reply"),
**split into skills**. The runtime auto-builds the skill index from
the typed resources; the model loads them on demand.

For custom tools you call **`tools-update`** with `{ description,
args_schema, source }`. The janitor runs an AST shape check + esbuild
compile **synchronously inside the PUT** — a bad shape returns 422
with structured diagnostics in the `errors[]` array, and the bundle
is left untouched. You never write `compiled.js`; it's generated.

#### The exact `source.ts` shape the runner expects

The custom-tool runtime contract is non-obvious and has burned past
sessions for hours. The runner's sandbox loader reads
`module.exports.default ?? module.exports` and requires it to be:

```ts
{
    id?: string,                 // optional; defaults to spec.tools[].id
    actions: {
        default: (args, ctx) => unknown | Promise<unknown>,
        // additional named actions are allowed but the runner ALWAYS
        // dispatches with action="default". A tool without
        // actions.default will load successfully but never fire.
    }
}
```

The canonical `source.ts` template:

```ts
type Args = {
  // declare your args inline so TS catches mistakes
  name: string
}

type Ctx = {
  secrets: {
    ref: (name: string) => string // opaque nonce, safe to log
    value: (name: string) => string // raw value — only for outbound calls
  }
  http: {
    fetch: (url: string, init?: RequestInit) => Promise<Response>
  }
}

export default {
  actions: {
    default: async (args: Args, ctx: Ctx) => {
      const res = await ctx.http.fetch(`https://api.example.com/hello?name=${args.name}`, {
        headers: { Authorization: `Bearer ${ctx.secrets.value('EXAMPLE_API_KEY')}` },
      })
      const data = await res.json()
      return { ok: true, data }
    },
  },
}
```

**Common shapes that look right and fail:**

| You wrote                                              | What compiles                  | Why it fails                                                                          |
| ------------------------------------------------------ | ------------------------------ | ------------------------------------------------------------------------------------- |
| `export default async function run(args) { ... }`      | `exports.default = <function>` | Loader needs `{actions: {default: fn}}` — a bare function has no `actions` property   |
| `export default { id: 'x', run: async (args) => ... }` | `exports.default = {id, run}`  | `actions` is missing entirely → freeze fails with "actions is missing or not object"  |
| `export default { actions: { run: async () => ... } }` | wrong key                      | `actions.run` exists, `actions.default` doesn't — the dispatcher fires `default` only |
| `module.exports = async function run() { ... }`        | CJS bare function              | Same as the first row — no `actions` map                                              |

The **upload** step (`tools-update`) AST-checks the source and
rejects any of the above with the exact reason in `errors[0].kind` +
`errors[0].message`. If you get `tool_compile_failed`, read the
diagnostic — it tells you the exact shape you missed. Do NOT retry
by tweaking the export style; the contract is `{actions: {default:
fn}}` and nothing else.

Use the **single-resource** typed PUTs (`tools-update`,
`agent-md-update`) and `skill-refs-update` for individual edits. There is
no bulk bundle-replace verb — edit the one resource that changed rather
than rewriting the whole bundle. Skills are authored in the store
(`llm-skills-create`) and pinned with `skill-refs-update`, never inline.

## Phase 6 — validate

`posthog__agent-applications-revisions-validate-create`. Returns
`{ ok, revision_id, revision_state, errors, resolved_natives }`. Fix
every error before freeze — they block.

### Why orphan diagnostics went away

In the legacy file-grain world the validator emitted
`orphan_custom_tool_dir` / `orphan_skill_file` when bundle files
existed but no spec entry referenced them. With the typed authoring
API those diagnostics are impossible: `spec.skills[]` and `spec.tools[]`
are **derived** from the typed resources at freeze, so a resource
that exists ALWAYS has a matching spec entry. You can't drift them.

If you see leftover orphan-diagnostic prose in older docs, it's stale.

## Phase 7 — freeze + test

Load the `running-and-evaluating-tests` playbook. Write 3-5 test cases
covering the happy path, the obvious edge cases, and one hostile
input.

`posthog__agent-applications-revisions-freeze-create` then
`agent-applications-revisions-test-run`. Read the results,
iterate.

If tests fail: branch a new draft from the just-frozen ready,
fix, re-freeze, re-test. (Same loop as
the `editing-agents-safely` playbook.)

## Phase 8 — promote

Explicit confirmation, as always.
`posthog__agent-applications-revisions-promote-create`.

For high-stakes agents (production-traffic-affecting, customer-
visible, money-moving), **suggest a preview link first** (per
`agent-authoring-flow.md` §2 phase 6, when the feature ships).
The user can drive a real conversation against the `ready`
revision before promoting.

## Anti-patterns to spot

- **The mega-spec.** User says "and also...", and the agent grows
  10 tools, 8 skills, 3 triggers. Push back: "let's get v1
  working with the core flow, then iterate. Each tool is
  cognitive load on the model."
- **The bare prompt.** No skills, no examples, just "be a great
  assistant for X". Will work for trivial cases, fail for
  anything specific. Push depth into skills.
- **Premature custom tooling.** User reaches for a custom tool
  before checking native ones. Cross-check `posthog__agent-native-tools-list`
  first — half the time the native tool exists.
- **Secrets in `agent.md`.** Comes up often. Refuse hard, load
  the `secrets-and-integrations` playbook.
- **Public auth on a chat trigger.** Will be abused. Default to
  `posthog` and explain why.

## What "good" looks like at v1

A v1 agent does ONE thing well, with:

- A spec under ~50 lines
- An `agent.md` under ~200 lines
- 0-3 skills, each under ~200 lines
- 3-5 test cases covering happy + edges
- One trigger
- The minimum tool surface

Anything more is v2.
