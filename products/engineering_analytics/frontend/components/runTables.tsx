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
 * A default-branch push has no PR association when it runs, so its only attribution is the backend's
 * `commit_pr_number`, the PR whose merge produced the head commit. The direct association wins.
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
    // A positive under a cent shows as "<$0.01", because "$0.00" would read as free.
    if (usd > 0 && usd < 0.01) {
        return '<$0.01'
    }
    return `$${usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatMinutes(minutes: number | null): string {
    return minutes == null ? '—' : `${Math.round(minutes).toLocaleString()} min`
}
