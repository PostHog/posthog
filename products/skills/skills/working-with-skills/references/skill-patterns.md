# Skill patterns (a cookbook)

A catalog of the shapes that shared skills in the PostHog skills store tend to take.
Most useful skills are a variation on one of these.
Pick the closest shape, copy its file layout and maintenance contract, and adapt it to the job.

A skill in the store is more than a prompt.
It is a small, versioned, shared memory that any agent on any surface (a local coding agent, a cloud task, Slack, PostHog Desktop) can load by name, and that agents with write access can update.
The patterns below lean on those three properties: **shared**, **versioned**, and **agent-writable**.

This is a living reference.
Add a pattern when a new shape proves itself over many sessions.

## Contents

- The patterns at a glance
- Project hub
- Big-build hub
- Ownership catalog
- Learning runbook
- Personal queue / daily driver
- Handover
- Thinking document
- Skill that runs itself (scout)
- House-style skill
- Bridge skill
- Cross-cutting techniques
- Picking and combining

## The patterns at a glance

| Pattern                           | Use it when…                                                                                                                | Starting point                                   |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| **Project hub**                   | an area of work runs over many sessions and you are tired of re-explaining where things stand.                              | `project-template` in the community store        |
| **Big-build hub**                 | one large feature has a spec, a backlog, a PR stack, and reviewers who all need the same context.                           | a project hub plus a design doc and decision log |
| **Ownership catalog**             | a team owns many PostHog objects (warehouse views, dashboards, alerts, scanners) and the context about them lives in heads. | an index body plus one reference per group       |
| **Learning runbook**              | the same class of problem gets debugged again and again, and each investigation teaches something.                          | rules-first body plus `investigations/`          |
| **Personal queue / daily driver** | one person wants a daily "what needs me next" view across the inbox, GitHub, or tickets.                                    | `my-inbox` in the community store                |
| **Handover**                      | work passes to a teammate (holiday, rotation, reorg) and they need both the facts and a way into them.                      | a message whose bullets are skill names          |
| **Thinking document**             | a plan or draft evolves over weeks with an agent's help, and every revision matters.                                        | a single-body skill with small edits             |
| **Skill that runs itself**        | a skill describes a job you do on a schedule, and the job could run without you.                                            | `authoring-scouts`                               |
| **House-style skill**             | a team maintains many skills and wants them to stay lean and consistent.                                                    | `skills-best-practices` in the community store   |
| **Bridge skill**                  | an agent supports local skill files and you want a one-word shortcut into the store.                                        | the bridge in the skills docs                    |

## Project hub

A hub for one area of work.
An agent starts a session with "resume <area> work", reads where things stand, does the work in the repo or product, and writes back what changed.
The skill is the memory, and the memory is readable: anyone can open the skill and see what the agents believe is true.

Typical layout:

```text
SKILL.md                 # what the area is, the file map, the session loop
HANDOVER.md              # one section per workstream; read first, overwrite last
CHANGELOG.md             # one line per session, rolling window (e.g. 14 days)
open-prs.md              # PRs in flight and their state
environment-notes.md     # durable gotchas that stay true
issues/INDEX.md          # numbered backlog index
issues/NN-<slug>.md      # one file per tracked issue
ideas/NN-<slug>.md       # one file per idea not yet committed to
```

The session loop the body describes:

1. Load the skill. Read `HANDOVER.md` and the backlog index.
2. Do the work where it belongs (code, product, queries), not in the skill.
3. At the end, file new issues or ideas, update `open-prs.md`, add one changelog line, and overwrite your own handover section.

The most important part of the body is a rule for where each fact goes.
Without it, an agent writes durable detail into whichever file it was already editing, usually the changelog.

| Still true in 30 days? | Has an owner who refreshes it? | Goes in                                        |
| ---------------------- | ------------------------------ | ---------------------------------------------- |
| Yes                    | Yes, a tracked work item       | `issues/NN` or `ideas/NN`                      |
| Yes                    | No, durable reference          | `environment-notes.md` or a `references/` file |
| No, but in flight now  | You, this session              | your `HANDOVER.md` section                     |
| No, it just happened   | Nobody                         | `CHANGELOG.md`, one line                       |

Pitfalls:

- One hub for everything. Make one hub per area, and add a **Companions** section that says what each sibling hub owns.
- A handover that turns into a log. It is a clobber file: each session replaces its own section, and a section goes when its work lands.
- A changelog that turns into an archive. Trim it as you append to it.

## Big-build hub

A project hub scaled up for one large feature with many moving parts.
Every person or agent that touches the feature loads one skill and gets the full picture.

Files that earn their place in addition to the project hub layout:

- `design.md`: the spec, trust boundaries, open questions, the options ruled out, and a dated **decision log**. The body tells agents to check the log before they reopen a question.
- `TODO.md`: the backlog, split by when each item can happen (now, after the current stack lands, blocked on a decision). PRs and review replies cite items by id.
- `stack-plan.md`: how a large branch splits into reviewable PRs, with per-PR checks.
- `reviewer-brief.md`: a one-page entry point you can hand to a reviewer as-is.
- `local-testing.md`: how to run the thing end to end, including the failure modes that produce silently wrong output.
- `scripts/`: helpers for repetitive mechanics, such as slicing or replaying stack layers.

When a reviewer asks "why this way?", the answer is a dated decision-log entry, not a person.

## Ownership catalog

An index of PostHog objects a team owns, with the context that the objects themselves cannot hold: what each one is for, how it connects to the rest, and the gotchas that bite when you read it.
Good subjects are warehouse views, dashboards, alerts, Replay Vision scanners, and endpoints.

Shape:

- The body is a short index: the two or three rules an agent gets wrong if it skips them, then a map from object group to reference file.
- `references/` holds one file per group (for example, one per view family).
- `recipes/` holds queries that are known to work, so agents copy instead of re-deriving.

The catalog also drives changes to the objects.
Before an agent creates a new alert or view, it reads the catalog to check for an existing one, then adds the new object to the catalog as part of the same change.
When something fires or breaks, the agent loads the catalog first to get the object's purpose, baseline, and history.

Pair a catalog with a **steward scout** that checks the objects on a schedule and updates the skill when it fixes something.
See the maintainer / steward pattern in `authoring-scouts`.

## Learning runbook

A read-only diagnostic runbook that gets better every time it is used.

Shape:

- **Rules before queries.** The body opens with the few rules that cause wrong answers when skipped, such as time zones, identity resolution across accounts, or which data source is fresh.
- **Pick an avenue.** A list that routes each symptom to one reference file and its recipes.
- **`investigations/`.** A dated write-up for each new class of issue.

The maintenance contract is the part that makes it learn.
The body says: every time an investigation finds a new class of issue, write it up in `investigations/` and extend the matching reference.
The next agent then starts from the last agent's findings instead of from zero.

## Personal queue / daily driver

A skill that answers "what needs me next?" for one person, across the inbox, GitHub, tickets, or accounts.
It renders one line per item with its state and a next action.

Shape:

- `scripts/` do the mechanical work: fetch from the APIs, rank, and render a table. Scripts give the same output every run, which prose instructions do not.
- `working-set.md` records only the items the person chose to own.
- The body puts **live data first, memory second**: the API is the truth, and the working set is a list of commitments. Never report status from the file alone.

A queue skill often pairs with a scout that runs it on a schedule and keeps one living report current, so the answer is ready before the person asks.
The community store has a generic starting point, `my-inbox`.

## Handover

When work passes to someone else, write the handover as links to skills rather than as prose.
Each bullet names a skill (the project hub, the runbook, the catalog) and says when to use it.

This works because the store is shared.
The handover reaches the person and their agent at the same time.
They do not need to paste context into their own agent: they say "use the <name> skill in the PostHog MCP to help here", and their agent gets the same context the author's agent had.

## Thinking document

A skill does not have to be instructions.
A plan, a quarterly draft, or a research note that evolves over weeks with an agent's help also fits well:

- The agent reads it on any surface and edits it with small `edits`.
- Every revision is a version you can diff.

Keep it as one body until it outgrows one screen, then split sections into `references/`.

## Skill that runs itself (scout)

Every Signals scout is a skill with a schedule.
When a skill describes a job you do regularly (check a catalog, sweep a queue, audit a fleet), turning it into a scout is a small step.
Some useful scouts maintain other skills: a steward that keeps a catalog current, or a reviewer that checks recently changed skills against the house style.

See `authoring-scouts` for the scout format, and `working-with-scouts` to delegate a watch without writing one.

## House-style skill

A team that maintains many skills benefits from one skill that says how skills are written: the spec floor, the team's patterns, a smell checklist, and a refactoring workflow.
Tell agents to load it before they create or edit a skill.
It should follow its own rules: a thin body and the substance in bundled files.

The community store has `skills-best-practices` as a starting point, and `skills-spec`, which is the Agent Skills specification as a skill.

## Bridge skill

If an agent supports local skill files, a tiny local skill can point at the `skills-store` skill so a short command (for example `/phs`) loads the store.
Keep the bridge thin, so updates to the store skill reach everyone without a local change.
The PostHog AI plugin already includes `skills-store`, so plugin users do not need a bridge.

## Cross-cutting techniques

- **Give every agent-maintained skill a convention.** A skill with no rule for where things go is a blank page, and agents fill blank pages with noise. State where each kind of fact goes and what the end-of-session write looks like.
- **Keep the body to about one screen.** The body is an index: what this is, the gotchas that bite hardest, the file map, companions, and the maintenance contract. New detail goes in a bundled file, and the body gains only a pointer.
- **Bound every growing file.** Rolling windows for changelogs, clobber sections for handovers, one file per issue. Anything that only grows eventually costs more to load than it saves.
- **Keep every file reachable from the body.** A file that no index links is invisible to progressive disclosure.
- **Link instead of copying.** A Companions section or a `Related skills` footer costs one line. A copied paragraph drifts.
- **Dogfood in the same session.** Use the skill for its real job. Where the agent stumbled or you had to supply context by hand, fix the skill before you finish.
- **Use the smallest write.** `edits` and `file_edits` with a chained `base_version`, as the main skill body describes. A full-body rewrite for a small change can silently drop content.

## Picking and combining

Most real skills combine two or three patterns.
A big-build hub is a project hub with a design doc.
A catalog is often paired with a runbook for the same objects, and both are often kept current by a steward scout.
A personal queue becomes a scout once its output is worth having before you ask.

If no pattern fits, start with the smallest skill that holds the context you keep re-explaining.
Add structure when you see the same kind of fact written in the wrong place twice.
