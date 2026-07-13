import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'

import type { CostSummary, HealthSummary } from '../lib/runHealth'
import { HealthKpi, STATE_META } from './healthVerdict'
import { RangeBar } from './RangeBar'
import { formatCost } from './runTables'

function formatDuration(seconds: number | null): string {
    return seconds == null ? '—' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

/** Duration spread as a range bar: median is the fill, p95 the tick. */
function DurationRange({ median, p95 }: { median: number | null; p95: number | null }): JSX.Element {
    // Scale a touch past p95 so its tick sits inside the bar rather than hard against the end.
    const scale = p95 ? p95 * 1.25 : 0
    return (
        <div className="flex flex-col gap-1">
            <span className="text-xs text-tertiary">Duration p50 → p95</span>
            <div className="flex items-center gap-2">
                <RangeBar
                    className="w-20"
                    fraction={scale ? Math.min(1, (median ?? 0) / scale) : 0}
                    tickFraction={scale ? p95! / scale : null}
                    tooltip={`median ${formatDuration(median)} · p95 ${formatDuration(p95)}`}
                />
                <span className="text-xs whitespace-nowrap tabular-nums text-secondary">
                    {formatDuration(median)} → {formatDuration(p95)}
                </span>
            </div>
        </div>
    )
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
 * Verdict strip above a workflow's runs: colored state word + pass rate, plus rollups the chart can't
 * show (re-run rate, total CI cost).
 */
export function WorkflowHealthHeader({ summary, cost, truncated, className }: WorkflowHealthHeaderProps): JSX.Element {
    const meta = STATE_META[summary.state]
    const passRateLabel = summary.passRate == null ? '—' : percentage(summary.passRate, 0)
    const hasCost = cost?.estimatedCostUsd != null

    return (
        <LemonCard
            hoverEffect={false}
            // Left accent in the state color so the strip reads healthy/degraded/failing at the edge.
            className={cn(
                'flex flex-wrap items-center gap-x-6 gap-y-4 border-l-4 px-5 py-4',
                meta.borderClass,
                className
            )}
        >
            <div className="flex flex-col">
                <div className="flex items-center gap-2">
                    <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', meta.dotClass)} />
                    <span className={cn('text-xl font-semibold leading-none', meta.wordClass)}>{meta.word}</span>
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

            {/* Rollups not on the chart: median is the chart's dashed line (omitted); p95, re-run rate,
                and cost aren't. */}
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
                <DurationRange median={summary.medianSeconds} p95={summary.p95Seconds} />
                {hasCost && <HealthKpi label="CI cost" value={`≈ ${formatCost(cost?.estimatedCostUsd ?? null)}`} />}
            </div>
        </LemonCard>
    )
}
