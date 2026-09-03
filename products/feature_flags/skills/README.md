# Feature flag skills

Agent skills owned by team-feature-flags.
Built by `hogli build:skills` and shipped in `dist/skills.zip` — see [products/posthog_ai/skills/README.md](../../posthog_ai/skills/README.md) for the pipeline.

| Skill                             | Job                                                                       |
| --------------------------------- | ------------------------------------------------------------------------- |
| `cleaning-up-stale-feature-flags` | Find flags that no longer serve a purpose and remove them safely.         |
| `copying-flags-across-projects`   | Duplicate a flag into other projects in the same organization.            |
| `finding-deleted-feature-flags`   | List flags soft-deleted in a time window, with who deleted each and when. |

## `instrument-feature-flags` is not ours, and must not be added here

The skill that teaches an agent to put code behind a PostHog flag is authored in [PostHog/context-mill](https://github.com/PostHog/context-mill), not in this repository.
It is the skill a person gets from "put this behind a feature flag", from the **Add feature flag** button in PostHog Desktop, and from `/instrument-feature-flags`.

- **Source:** `context/skills/omnibus/instrument-feature-flags/{config.yaml,description.md}`.
  `description.md` is the hand-written SKILL.md body.
  The per-platform `references/` are generated at build time from the `docs_urls` in `config.yaml`, so the SDK guidance tracks posthog.com instead of being maintained by hand.
  The per-platform variants live beside it in `context/skills/feature-flags/`.
- **Owner:** `@PostHog/team-wizard-docs`, via the default entry in context-mill's CODEOWNERS.
  A product team takes over a skill tree there by adding a path entry, the way team-error-tracking and team-self-driving already have.
- **Distribution:** a context-mill release publishes `skills-mcp-resources.zip`, a zip of zips.
  Consumers pull `omnibus-instrument-feature-flags.zip` out of it and strip the `omnibus-` prefix from both the directory name and the `name:` frontmatter, which is why the installed skill is called `instrument-feature-flags`.

Every shipping consumer overlays context-mill on top of this repository's skills, not under it — the [handbook lists the merge sites](../../../docs/published/handbook/engineering/ai/writing-skills.md#context-mill-skills-override-this-repos).
So a `products/feature_flags/skills/instrument-feature-flags/` directory would not replace the shipping skill.
Its `SKILL.md` would be overwritten, any extra reference file would survive as an orphan inside someone else's skill, and the two sources would drift with no signal.
The only place the monorepo copy would win is `hogli sync:skill`, which is local development.

Local builds are the mirror image: they carry no omnibus skills at all, because `LocalSkillsCache.ensure_built()` renders only `products/*/skills/` and wipes the dist dir first.
That is why the eval below guards for the skill instead of assuming it is installed.

So:

- **Do not add `instrument-feature-flags` under `products/*/skills/`.**
  Change the context-mill source instead.
- **Do not add a second skill covering the same trigger**, for example `wrapping-code-in-feature-flags`.
  Two entry points for one job means agents pick one at random and the two drift.
  A rename needs an atomic rename and migration agreed with the skills-distribution owner.
- The same applies to the other five omnibus skills: `instrument-integration`, `instrument-product-analytics`, `instrument-error-tracking`, `instrument-llm-analytics`, and `instrument-logs`.

Baseline trigger coverage lives in [`products/feature_flags/evals/eval_instrument_flags.py`](../evals/eval_instrument_flags.py).
It grades the context-mill skill itself, so it needs that skill present in the sandbox and refuses to run without it — read its module docstring before running it.

`hogli lint:skills` fails when any of the six omnibus names appears under `products/*/skills/`, so the rule above is enforced rather than trusted.
