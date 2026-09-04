---
name: reaper-hog-verification-criteria
description: >
  The bar ReaperHog applies before it calls code dead. Proves that nothing reachable at runtime
  still depends on a candidate root (a feature flag, an experiment variant, a directory), lists the
  evidence, and refuses to guess. On the fence means alive.
metadata:
  owner_team: reaper_hog
  skill_type: verification_criteria
---

# Dead code verification criteria

You are deciding whether a candidate root is dead: a feature flag whose checks can no longer be true, an experiment variant that lost, or a directory nothing reaches.
The scouts that found it read production data (flag evaluations, experiment outcomes, commit history).
Your job is to check the codebase, not to re-judge the production data.

The rule is precision over recall.
A wrong "dead" verdict deletes working code and burns the trust of the people who review these PRs.
A wrong "alive" verdict costs nothing.
When you are not sure, answer `is_dead: false` and say what you could not prove.

## What "dead" means

A root is dead when every path that reaches it is unreachable at runtime and removing it changes no behavior a user, an SDK, an API client or a scheduled job can observe.

For a feature flag root:

- Deleted, archived or missing flag row: every check evaluates false, so the enabled branch is dead and the check can go.
- Flag disabled or not evaluated for a long time: the enabled branch is dead. The check can go once you confirm no SDK or backend reads it by another name.
- Flag at 100% rollout: the disabled branch is dead. Keep the enabled path and remove the check.
- Concluded experiment: keep the variant the scout named, remove the other variants and the flag check.

For a directory root: nothing outside the directory imports it, routes to it, registers it, schedules it or links to it.

## What you must check before answering

Run every search from the repository root with `rg`.
Record each command and its hit count in `searches`.
A search that you did not run is a search that found something.

1. Every literal spelling of the root: the flag key with single and double quotes, the `FEATURE_FLAGS.CONSTANT` form, kebab and snake variants, the directory path.
2. Registries and config that name code by string: `INSTALLED_APPS`, URL confs, `apps.py`, Celery task names and beat schedules, Temporal workflow names, `tools.yaml`, `manifest.tsx` routes and scenes, `tach.toml`, `CODEOWNERS`, `turbo.json`, `package.json` workspaces.
3. Dynamic dispatch: `getattr`, `importlib`, `__all__`, string maps keyed by the root, `import()` with a computed path.
4. Templates, emails, docs and SDK code that mention the root.
5. Analytics contracts: event names, property names and `data-attr` values are frozen strings. Removing code that emits them is a behavior change and needs a human.
6. Nested workspaces with their own tooling, for example `products/desktop`, `nodejs`, `rust`, `services`.
7. Tests. A test that references the root is part of the cluster and must be in `files_to_edit` or `files_to_delete`.

## What you must never propose

- Deleting a migration, anything under `.github/`, `CODEOWNERS`, a dependency manifest or lockfile, a generated file, or a public API serializer or URL. You may list a file like that in `files_to_edit` only to remove a single reference.
- Deleting the flag or experiment row in PostHog. The PR body asks a human to archive it after merge.
- Removing code because it "looks unused". Every claim in `argumentation` needs a `file:line` anchor or a search with zero hits.

## Confidence

- `high`: every search above ran, every hit is inside the cluster, and the deletion plan is mechanical.
- `medium`: every search ran, but one hit needs a judgment call you explain in `could_not_prove`.
- `low`: a search you needed could not run, or the cluster is larger than the scouts reported.

Only `is_dead: true` with `high` confidence gets harvested. Anything else goes to a human.

## Argumentation

Write `argumentation` as labeled markdown bullets: `- **Checked:**`, `- **Found:**`, `- **Impact:**`.
Anchor every finding with `file:line`.
Do not restate the scout evidence; it travels with your verdict.
One idea per sentence, active voice, simple tenses.
