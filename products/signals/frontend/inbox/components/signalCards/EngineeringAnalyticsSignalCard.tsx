import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { percentage } from 'lib/utils/numbers'
import type { SignalNode } from 'scenes/debug/signals/types'

import type {
    EngineeringAnalyticsCIBrokenDefaultBranchSignalExtraApi,
    EngineeringAnalyticsCIDurationRegressionSignalExtraApi,
    EngineeringAnalyticsCIFlakyCheckSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'
import { SignalSourceProduct, SignalSourceType } from 'products/signals/frontend/inbox/types'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

type RepoWorkflowExtra = Record<string, unknown> & { repo_owner: string; repo_name: string; workflow_name: string }

/** Every engineering_analytics CI signal carries repo + workflow identity; the rest is per-type. */
function hasRepoWorkflow(value: unknown): value is RepoWorkflowExtra {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return (
        typeof extra.repo_owner === 'string' &&
        typeof extra.repo_name === 'string' &&
        typeof extra.workflow_name === 'string'
    )
}

/** The headline metric line, switched on the CI signal variant. */
function metricLine(signal: SignalNode): string | null {
    const extra = signal.extra
    switch (signal.source_type) {
        case SignalSourceType.CiFlakyCheck: {
            const e = extra as Record<string, unknown> & EngineeringAnalyticsCIFlakyCheckSignalExtraApi
            return `Flaky · ${e.job_name} · ${e.flaky_count} runs in ${e.window_days}d`
        }
        case SignalSourceType.CiBrokenDefaultBranch: {
            const e = extra as Record<string, unknown> & EngineeringAnalyticsCIBrokenDefaultBranchSignalExtraApi
            return `${e.branch} · ${percentage(e.conclusive_success_rate, 0)} pass`
        }
        case SignalSourceType.CiDurationRegression: {
            const e = extra as Record<string, unknown> & EngineeringAnalyticsCIDurationRegressionSignalExtraApi
            return `p95 +${percentage(e.pct_increase, 0)}`
        }
        default:
            return null
    }
}

/** Inbox card for engineering_analytics CI signals (flaky check, broken default branch, duration regression). */
export function EngineeringAnalyticsSignalCard({ signal }: SignalCardProps): JSX.Element {
    if (!hasRepoWorkflow(signal.extra)) {
        return <SignalCardShell signal={signal}>{null}</SignalCardShell>
    }
    const { repo_owner, repo_name, workflow_name } = signal.extra
    const metric = metricLine(signal)

    return (
        <SignalCardShell signal={signal}>
            <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-tertiary">
                    {repo_owner}/{repo_name}
                </span>
                <span className="font-medium text-sm">{workflow_name}</span>
            </div>
            {metric && <div className="text-xs text-tertiary mt-1">{metric}</div>}

            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mt-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}
        </SignalCardShell>
    )
}

export const engineeringAnalyticsSignalCardEntry: SignalCardEntry = {
    key: 'engineering_analytics',
    matches: (signal: SignalNode) =>
        signal.source_product === SignalSourceProduct.EngineeringAnalytics && hasRepoWorkflow(signal.extra),
    Component: EngineeringAnalyticsSignalCard,
}
