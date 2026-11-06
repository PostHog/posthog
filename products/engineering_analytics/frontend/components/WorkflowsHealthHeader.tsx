import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'

import { percent } from '../lib/format'
import type { FleetSummary } from '../lib/runHealth'
import { HealthKpi, STATE_META } from './healthVerdict'
import { formatCost } from './runTables'

interface WorkflowsHealthHeaderProps {
    summary: FleetSummary
    /** Workflow list was capped server-side, so totals cover the top N by run count, not the whole fleet. */
    truncated?: boolean
    /** Reloading on a window/branch change: show a skeleton so the old numbers don't read as current. */
    loading?: boolean
    className?: string
}

/** Verdict strip above the all-workflows table: state word, failing-now count, pass rate, re-runs,
 *  total runs, and CI spend rolled up across every workflow in the window. */
export function WorkflowsHealthHeader({
    summary,
    truncated,
    loading,
    className,
}: WorkflowsHealthHeaderProps): JSX.Element {
    const meta = STATE_META[summary.state]
    const passingNow = summary.settledWorkflows - summary.failingNow
    const passingRateLabel = summary.settledWorkflows > 0 ? percent(passingNow / summary.settledWorkflows) : '—'
    // Name what's failing rather than restate the Failing-now / Workflows counts already in the KPI row.
    const failingLabel =
        summary.failingWorkflowNames.length > 0
            ? `${summary.failingWorkflowNames.slice(0, 3).join(', ')}${
                  summary.failingNow > 3 ? ` +${summary.failingNow - 3} more` : ''
              } failing`
            : `${summary.failingNow} failing`
    const hasCost = summary.estimatedCostUsd != null

    if (loading) {
        return (
            <LemonCard
                hoverEffect={false}
                className={cn(
                    'flex flex-wrap items-center gap-x-6 gap-y-4 border-l-4 border-l-transparent px-5 py-4',
                    className
                )}
            >
                <LemonSkeleton className="h-7 w-40" />
                <LemonSkeleton className="h-7 w-16" />
                <div className="flex-1" />
                <LemonSkeleton className="h-7 w-72" />
            </LemonCard>
        )
    }

    return (
        <LemonCard
            hoverEffect={false}
            // Left accent in the state color (border-l-4 + the state's token class).
            className={cn(
                'flex flex-wrap items-center gap-x-6 gap-y-4 border-l-4 px-5 py-4',
                meta.borderClass,
                className
            )}
        >
            <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                    <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', meta.dotClass)} />
                    <span className={cn('text-xl font-semibold leading-none', meta.wordClass)}>{meta.word}</span>
                </div>
                <span className="text-xs text-secondary">
                    {summary.workflowCount === 0
                        ? 'No workflow runs in this window'
                        : summary.settledWorkflows === 0
                          ? `${summary.workflowCount} workflows · no completed runs yet`
                          : summary.failingNow > 0
                            ? failingLabel
                            : summary.flakyNow > 0
                              ? `${summary.flakyNow} flaky · below 90% pass rate`
                              : truncated
                                ? 'All shown workflows healthy'
                                : `All ${summary.workflowCount} workflows healthy`}
                </span>
                {truncated && (
                    <span className="text-xs text-tertiary">
                        Top {summary.workflowCount} workflows by run count. All summary values use this set.
                    </span>
                )}
            </div>

            <div className="flex flex-col border-l border-primary pl-6">
                <Tooltip
                    title={`Share of workflows whose latest run did not fail, of the ${summary.settledWorkflows} with a completed run. A cancelled, skipped or neutral latest run counts as not failing. This is per workflow and current, unlike the run pass rate, which weighs every run.`}
                >
                    <span className="self-start cursor-default text-xs text-tertiary">Not failing now</span>
                </Tooltip>
                <span className="text-2xl font-semibold leading-7 tabular-nums">{passingRateLabel}</span>
            </div>

            <div className="flex-1" />

            <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
                <HealthKpi
                    label="Re-runs"
                    value={
                        <Tooltip title="Runs with attempt > 1 in the window. Frequent re-runs usually point to flaky checks.">
                            <span>{summary.rerunCycles.toLocaleString()}</span>
                        </Tooltip>
                    }
                />
                <HealthKpi
                    label="Total runs"
                    value={
                        <Tooltip
                            title={
                                truncated
                                    ? `Covers the top ${summary.workflowCount} workflows by run count. Workflows with fewer runs are left out.`
                                    : undefined
                            }
                        >
                            <span>{summary.totalRuns.toLocaleString()}</span>
                        </Tooltip>
                    }
                />
                {hasCost && <HealthKpi label="CI cost" value={`≈ ${formatCost(summary.estimatedCostUsd)}`} />}
            </div>
        </LemonCard>
    )
}
