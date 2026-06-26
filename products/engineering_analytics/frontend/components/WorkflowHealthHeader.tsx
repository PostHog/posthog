import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'

import type { CostSummary, HealthSummary } from '../lib/runHealth'
import { HealthKpi, STATE_META } from './healthVerdict'
import { formatCost } from './runTables'

function formatDuration(seconds: number | null): string {
    return seconds == null ? '—' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

interface WorkflowHealthHeaderProps {
    summary: HealthSummary
    /** Cost rollup for the window; null (or all-null fields) hides the cost KPI when jobs aren't synced. */
    cost: CostSummary | null
    /** Runs list was capped server-side — run rollups are over the most recent runs, not the full window. */
    truncated?: boolean
    className?: string
}

/**
 * The verdict strip above a workflow's runs: a colored state word + pass rate carry the answer (is this
 * workflow ok?) before the eye reaches the chart, with the headline rollups the chart can't show —
 * re-run rate (flakiness) and total CI cost — alongside. Adapted from the CI master-health design to a
 * single workflow over the selected window.
 */
export function WorkflowHealthHeader({ summary, cost, truncated, className }: WorkflowHealthHeaderProps): JSX.Element {
    const meta = STATE_META[summary.state]
    const passRateLabel = summary.passRate == null ? '—' : percentage(summary.passRate, 0)
    const hasCost = cost?.estimatedCostUsd != null

    return (
        <div
            className={cn(
                'flex flex-wrap items-center gap-x-6 gap-y-4 rounded-lg border bg-surface-primary px-5 py-4',
                className
            )}
            // Left accent in the state color — the strip reads as healthy/degraded/failing at the edge.
            style={{ borderLeftWidth: 4, borderLeftColor: meta.color }}
        >
            <div className="flex flex-col">
                <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: meta.color }} />
                    <span className="text-xl font-semibold leading-none" style={{ color: meta.color }}>
                        {meta.word}
                    </span>
                    {summary.running > 0 && <LemonTag type={meta.tag}>{summary.running} running</LemonTag>}
                </div>
                <span className="mt-1.5 text-xs text-secondary">
                    {summary.state === 'unknown' ? (
                        'No completed runs in this window'
                    ) : summary.state === 'failing' ? (
                        <>
                            Latest run failed
                            {summary.lastFailureAt && (
                                <>
                                    {' · '}
                                    <TZLabel time={summary.lastFailureAt} />
                                </>
                            )}
                        </>
                    ) : (
                        `${summary.passedRuns} of ${summary.completedRuns}${truncated ? ' recent' : ''} runs passed`
                    )}
                </span>
            </div>

            <div className="flex flex-col border-l border-primary pl-6">
                <span className="text-2xl font-semibold leading-7 tabular-nums">{passRateLabel}</span>
                <span className="text-xs text-tertiary">
                    pass rate · {truncated ? 'recent ' : ''}
                    {summary.completedRuns} {truncated ? 'runs' : 'completed'}
                </span>
            </div>

            <div className="flex-1" />

            {/* Rollups the chart doesn't already show — median is the chart's dashed line, so it's omitted
                here; p95 (tail latency), re-run rate, and total cost aren't anywhere on the scatter. */}
            <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
                <HealthKpi
                    label="Runs"
                    value={
                        truncated ? (
                            <Tooltip
                                title={`Showing the most recent ${summary.totalRuns} runs. Failures and pass rate cover these; CI cost reflects the full window.`}
                            >
                                <span>{summary.totalRuns.toLocaleString()}+</span>
                            </Tooltip>
                        ) : (
                            summary.totalRuns.toLocaleString()
                        )
                    }
                />
                <HealthKpi label="Failures" value={summary.failures.toLocaleString()} danger={summary.failures > 0} />
                <HealthKpi label="Re-runs" value={summary.reruns.toLocaleString()} danger={summary.reruns > 0} />
                <HealthKpi label="p95 duration" value={formatDuration(summary.p95Seconds)} />
                {hasCost && <HealthKpi label="CI cost" value={`≈ ${formatCost(cost?.estimatedCostUsd ?? null)}`} />}
            </div>
        </div>
    )
}
