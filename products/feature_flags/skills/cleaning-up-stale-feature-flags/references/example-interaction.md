# Example interaction

One worked run of the workflow in `SKILL.md`, end to end.

```text
User: "Clean up our stale feature flags."

Agent steps:
- Call posthog:feature-flag-get-all with active: "STALE"
- For the most promising candidates, read status, definition, dependents, and schedules
- Confirm creation and update dates are older than 30 days and no linked system needs the flag
- Ask about product-tour usage; the user confirms that neither candidate is used by a tour
- Present findings:

   "I found 4 stale feature flags in your project:

   | Flag | Why stale | Rollout | Recommendation |
   |------|-----------|---------|----------------|
   | old-checkout-flow | No evaluations in 45 days | 100% boolean | Clean up now |
   | beta-dashboard-v2 | 100% rolled out, created 3 months ago | 100% boolean | Clean up now |
   | new-pricing-page | No evaluations in 60 days | 100%, tied to experiment | Excluded: check the experiment first |
   | promo-banner-test | No evaluations in 90 days | 40% partial | Excluded: needs a decision on which path to keep |

   old-checkout-flow is the safest candidate, so I'll start there."

- Search the repository for existing work on old-checkout-flow: only the commit that added the key matches,
  and no branch, commit, or open PR removes it
- Search the repository for "old-checkout-flow"; find a Flags.OLD_CHECKOUT constant
  and trace its two call sites
- Repeat the definition, status, dependents, and schedules reads: same version and updated_at, still 100% boolean
- Remove both checks, keep the enabled paths, delete the constant and a dead else branch;
  keep the generic isEnabled helper the removal orphaned, and note it for the report
- Run the checkout tests and the linter; both pass
- Ask whether to open a PR: "The cleanup is ready and the tests pass. Open a draft PR?"
- The user agrees. Re-run the open-PR search, then repeat the four reads right before publishing: same version, still 100% boolean
- Open one draft PR:
  "chore(feature-flags): remove old-checkout-flow"
- Report:

   "Done. The draft PR removes both checks of old-checkout-flow and keeps the current
   checkout behavior. The checkout tests pass and no references to the key remain.

   Nothing calls the generic isEnabled helper now. I left it in place, because removing
   it changes the flag abstraction rather than this flag. Delete it if you want to.

   I have not changed the flag in PostHog, and archiving is not automated yet. Once
   this PR is deployed (merged is not enough), come back and I'll check whether any
   other repository still references the flag. Then archive it in PostHog yourself.

   Want me to do beta-dashboard-v2 next?"
```
