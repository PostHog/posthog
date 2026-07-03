import { Tooltip } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import { percentage } from 'lib/utils/numbers'

import type { FleetSummary } from '../lib/runHealth'
import { HealthKpi, STATE_META } from './healthVerdict'
import { formatCost } from './runTables'

interface WorkflowsHealthHeaderProps {
    summary: FleetSummary
    /** Workflow list was capped server-side — totals cover the top N by run count, not the whole fleet. */
    truncated?: boolean
    className?: string
}

/**
 * Fleet verdict strip above the all-workflows table: colored state word + "% green" headline rolled up
 * across every workflow in the window (how many are red now, total runs, total CI spend).
 */
export function WorkflowsHealthHeader({ summary, truncated, className }: WorkflowsHealthHeaderProps): JSX.Element {
    const meta = STATE_META[summary.state]
    const greenNow = summary.settledWorkflows - summary.failingNow
    const greenRateLabel = summary.settledWorkflows > 0 ? percentage(greenNow / summary.settledWorkflows, 0) : '—'
    const hasCost = summary.estimatedCostUsd != null

    return (
        <LemonCard
            hoverEffect={false}
            // Left accent in the state color.
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
                </div>
                <span className="mt-1.5 text-xs text-secondary">
                    {summary.workflowCount === 0
                        ? 'No workflow runs in this window'
                        : summary.settledWorkflows === 0
                          ? `${summary.workflowCount} workflows · none settled yet`
                          : summary.failingNow > 0
                            ? `${summary.failingNow} of ${summary.workflowCount} workflows failing right now`
                            : summary.flakyNow > 0
                              ? `${summary.flakyNow} flaky · below 90% pass rate`
                              : summary.settledWorkflows < summary.workflowCount
                                ? `${summary.settledWorkflows} of ${summary.workflowCount} settled · all green`
                                : truncated
                                  ? `Top ${summary.workflowCount} by runs · all green`
                                  : `All ${summary.workflowCount} workflows healthy`}
                </span>
            </div>

            <div className="flex flex-col border-l border-primary pl-6">
                <span className="text-2xl font-semibold leading-7 tabular-nums">{greenRateLabel}</span>
                <span className="text-xs text-tertiary">green now · {summary.settledWorkflows} settled</span>
            </div>

            <div className="flex-1" />

            <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
                <HealthKpi
                    label="Workflows"
                    value={
                        truncated ? (
                            <Tooltip
                                title={`Showing the top ${summary.workflowCount} workflows by run count. Total runs, CI cost, and the verdict cover these — lower-volume workflows beyond the cap aren't included.`}
                            >
                                <span>{summary.workflowCount.toLocaleString()}+</span>
                            </Tooltip>
                        ) : (
                            summary.workflowCount.toLocaleString()
                        )
                    }
                />
                <HealthKpi
                    label="Failing now"
                    value={summary.failingNow.toLocaleString()}
                    danger={summary.failingNow > 0}
                />
                <HealthKpi label="Total runs" value={summary.totalRuns.toLocaleString()} />
                {hasCost && <HealthKpi label="CI cost" value={`≈ ${formatCost(summary.estimatedCostUsd)}`} />}
            </div>
        </LemonCard>
    )
}
