// Shared status tags and cost formatters for the CI run/job tables (PR detail and workflow-run pages).

import { LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { verdictTag } from '../lib/runStatus'

const STATUS_DOT: Record<string, string> = {
    success: 'bg-success',
    danger: 'bg-danger',
    warning: 'bg-warning',
    muted: 'bg-muted',
}

export function RunConclusionTag({ conclusion }: { conclusion: string | null }): JSX.Element {
    if (conclusion == null) {
        return <LemonTag type="completion">Running</LemonTag>
    }
    const tag = verdictTag(conclusion)
    return <LemonTag type={tag.type}>{tag.label}</LemonTag>
}

/** Dot + label status — quieter than a boxed tag down a long list. */
export function StatusDot({ conclusion }: { conclusion: string | null }): JSX.Element {
    const tag = verdictTag(conclusion)
    return (
        <span className="flex items-center gap-1.5 text-xs whitespace-nowrap">
            <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', STATUS_DOT[tag.type] ?? 'bg-muted')} />
            <span className="text-secondary">{tag.label}</span>
        </span>
    )
}

/**
 * The PR to show for a run, or null when it has none.
 *
 * A run that ran *for* a PR carries `pr_number`. A default-branch push has no PR association by the
 * time it runs, so its only attribution is the PR whose merge produced the head commit: the
 * backend's `commit_pr_number`. Prefer the direct association; fall back to the merge.
 */
export function runPrNumber(prNumber: number | null, commitPrNumber: number | null): number | null {
    if (prNumber != null && prNumber > 0) {
        return prNumber
    }
    return commitPrNumber != null && commitPrNumber > 0 ? commitPrNumber : null
}

export function formatCost(usd: number | null): string {
    if (usd == null) {
        return '—'
    }
    // Positives under a cent show as "<$0.01" — "$0.00" would read as free.
    if (usd > 0 && usd < 0.01) {
        return '<$0.01'
    }
    return `$${usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatMinutes(minutes: number | null): string {
    return minutes == null ? '—' : `${Math.round(minutes).toLocaleString()} min`
}
