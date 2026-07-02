---
name: review-hog-authoring
description: >
  How to author custom ReviewHog skills — the review perspectives, blind-spot checks, and
  validation criteria that drive ReviewHog's automated PR reviews. Use when a user wants a new
  review perspective (a specialist lens on their PRs), a custom blind-spot sweep, or their own
  validation bar for which findings get published. Covers the skill anatomy per kind, the naming
  contract and category, how to ground on the existing set before authoring, and how the user
  activates the result. Trigger on "create a ReviewHog perspective", "custom review perspective",
  "my own blind-spot check", "custom validation criteria", "tune what ReviewHog publishes".
metadata:
  owner_team: review_hog
  skill_type: authoring
---

# Authoring ReviewHog skills

**ReviewHog** is PostHog's automated PR reviewer. A review splits the PR into chunks, then for each
chunk runs every enabled **perspective** in parallel (independent specialist lenses), a single
**blind-spot check** afterwards (a final sweep conditioned on what the perspectives found), and
finally judges every surviving candidate finding against one **validation criteria** skill — only
findings that pass get published to the pull request.

All three kinds are team `LLMSkill` rows the review agents pull over MCP at run time. PostHog ships
canonicals; this skill is the guide for authoring **custom** ones. The skill itself is team-level;
whether it _runs_ is a per-user setting in **Inbox → Code review**.

| Kind                | Name contract                   | Cardinality per user                | Canonical example                          |
| ------------------- | ------------------------------- | ----------------------------------- | ------------------------------------------ |
| Review perspective  | `review-hog-perspective-<slug>` | Multi-enable, at least one stays on | `review-hog-perspective-logic-correctness` |
| Blind-spot check    | `review-hog-blind-spots-<slug>` | Exactly one active; selecting swaps | `review-hog-blind-spots-general`           |
| Validation criteria | `review-hog-validation-<slug>`  | Exactly one active; selecting swaps | `review-hog-validation-criteria`           |

## Authoring flow

1. **Ground yourself.** Using the PostHog MCP skill tools, `skill-list` the team's `review-hog-*`
   skills and `skill-get` the canonical of the kind you're authoring (see the table above) — it is
   the reference for structure and tone. For a perspective, skim the descriptions of every existing
   `review-hog-perspective-*` so the new lens doesn't re-cover ground an enabled one already owns
   (overlap gets deduplicated later, but it wastes review passes).
2. **Interview the user.** Ask what the skill should focus on, and offer a few concrete directions
   the current set doesn't cover — grounded in what you saw in step 1 and, when useful, in the
   project itself. Don't start writing until the direction is picked.
3. **Draft the body** following the per-kind guidance below. Keep it a focused instruction set the
   review agent can apply to one chunk in one pass — not an essay.
4. **Create the skill yourself with `posthog:skill-create`** — actually create the team `LLMSkill`
   row; never hand the user a body to copy-paste. Pass the exact name per the contract above
   (lowercase slug), a one-paragraph `description` of what the lens/sweep/bar is, and the body.
   **The name prefix is the whole identity** — it is how the Code review tab and the review runs
   discover the skill. There is no `category` parameter on the skill tools and you don't need one:
   the backend stamps the `review_hog` grouping category itself (it only affects grouping on the
   Skills page) — do not spend turns trying to set or verify it. Iterate with
   `posthog:skill-update` if the user wants changes. Author fresh — don't `skill-duplicate` a
   canonical to edit: seeded metadata rides along with the copy, and the canonical sync may
   overwrite or prune it.
5. **Tell the user how to activate it.** A custom skill starts inactive for them:
   - **Perspective** — toggle it on under Inbox → Code review → Perspectives (it appears disabled
     until they enable it; at least one perspective must stay on).
   - **Blind-spot check / validation criteria** — select it under the matching section; exactly one
     runs at a time, so selecting it swaps out the current one **for their reviews only**.
     Reviews pin skill versions when a run starts, so an edit mid-review applies from the next run.

## Writing a review perspective

The body instructs one specialist review pass over one PR chunk. It should define:

- **The lane** — what this lens is responsible for, and an explicit note that other concerns are
  covered by other perspectives (stay in lane; report everything in lane without worrying about
  overlap).
- **What to hunt** — a handful of concrete investigation areas with specific checks, not abstract
  virtues. The canonical logic-correctness skill's numbered "primary investigation areas" is the
  shape to match.
- **What to ignore** — the noise this lens must not report (style, speculation, things outside the
  diff's blast radius).
- **What a publishable finding looks like** — concrete, evidenced, tied to changed code, with a
  clear "why it matters".

## Writing a blind-spot check

The body instructs the final sweep that runs after every enabled perspective finished a chunk. It
is **conditioned on the covered findings** (the prompt lists which perspectives ran and what they
found), so the body should say how to use that: study where attention already went, then hunt
everywhere else — error paths, unhandled inputs, cross-file interactions, assumptions. It is not
scoped to one specialty, and an empty result beats padding. A custom sweep narrows or re-weights
this hunt (e.g. toward a domain the team keeps getting burned by).

## Writing validation criteria

The body defines the keep/drop bar every candidate finding is judged against before publishing.
Precision over recall is the house default — a reviewer that raises noise gets muted — so define:
what makes a finding real and worth an author's attention (user-affecting correctness, security,
data loss, contract breaks, performance), what gets dropped (overengineering, speculation,
defensive paranoia, unreachable edges, style), and how to treat genuine uncertainty (default:
drop). A custom bar shifts strictness or re-weights concerns; it should still demand evidence from
the live codebase, not vibes.
