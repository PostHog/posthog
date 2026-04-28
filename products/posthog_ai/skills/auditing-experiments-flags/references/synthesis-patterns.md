# Recurring patterns

Apply these patterns during **full audits** (both experiments and flags).
Each pattern looks for a cluster of related findings that together suggest a bigger problem.

## Experiment setup gaps

**Trigger**: 3+ experiments have PROCESS-category findings (missing hypothesis, no metrics, no conclusion).

**Message**:

> Multiple experiments lack key setup steps (hypothesis, metrics, or conclusions).
> This suggests the team may benefit from an experiment setup checklist or template.

## Flag hygiene debt

**Trigger**: 5+ flags have CLEANUP-category findings (stale drafts, fully rolled out, orphaned experiment flags).

**Message**:

> There are many flags that could be cleaned up. Consider scheduling a flag cleanup session
> to remove stale flags from the codebase and reduce unnecessary flag evaluations.

## Experiment-flag disconnection

**Trigger**: At least one experiment has a "stopped with active flag" finding AND at least one has a "mid-run flag change" finding.

**Message**:

> Some experiments have flags that were modified during their run, and others were stopped
> but their flags are still active. This suggests the experiment-flag lifecycle is not well-coordinated.
> Consider establishing a post-experiment cleanup process.

## Reporting patterns

When a pattern triggers:

1. Add a "Recurring patterns" section after individual findings.
2. List each triggered pattern with its message.
3. These are always INFO severity — they are observations, not individual findings.
