# Synthesis patterns

Apply these cross-finding patterns during **full audits** (both experiments and flags).
Each pattern looks for a cluster of related findings that together suggest a systemic issue.

## Process drift

**Trigger**: 3+ experiments have PROCESS-category findings (missing hypothesis, no metrics, no conclusion).

**Synthesis message**:

> Multiple experiments lack key methodology elements (hypothesis, metrics, or conclusions).
> This suggests the team may benefit from an experiment setup checklist or template.

## Flag hygiene debt

**Trigger**: 5+ flags have CLEANUP-category findings (stale drafts, fully rolled out, orphaned experiment flags).

**Synthesis message**:

> There are many flags that could be cleaned up. Consider scheduling a flag cleanup session
> to remove stale flags from the codebase and reduce evaluation overhead.

## Experiment-flag disconnection

**Trigger**: At least one experiment has a "stopped with active flag" finding AND at least one has a "mid-run flag change" finding.

**Synthesis message**:

> Some experiments have flags that were modified during their run, and others were stopped
> but their flags are still active. This suggests the experiment-flag lifecycle is not well-coordinated.
> Consider establishing a post-experiment cleanup process.

## Reporting synthesis

When a synthesis pattern triggers:

1. Add a "Systemic patterns" section after individual findings.
2. List each triggered pattern with its message.
3. These are always INFO severity — they are observations, not individual findings.
