import { cn } from 'lib/utils/css-classes'
import { percentage } from 'lib/utils/numbers'

import type { FleetSummary } from '../lib/runHealth'
import { HealthKpi, STATE_META } from './healthVerdict'
import { formatCost } from './runTables'

interface WorkflowsHealthHeaderProps {
    summary: FleetSummary
    className?: string
}

/**
 * Fleet verdict strip above the all-workflows table: the same colored state word + a "% green" headline
 * as the single-workflow header, but rolled up across every workflow in the window — how many are red
 * right now, total runs, and total CI spend. The duration scatter has no place here (no single run
 * list), so this strip is the at-a-glance answer for the whole page.
 */
export function WorkflowsHealthHeader({ summary, className }: WorkflowsHealthHeaderProps): JSX.Element {
    const meta = STATE_META[summary.state]
    const greenNow = summary.settledWorkflows - summary.failingNow
    const greenRateLabel = summary.settledWorkflows > 0 ? percentage(greenNow / summary.settledWorkflows, 0) : '—'
    const hasCost = summary.estimatedCostUsd != null

    return (
        <div
            className={cn(
                'flex flex-wrap items-center gap-x-6 gap-y-4 rounded-lg border bg-surface-primary px-5 py-4',
                className
            )}
            style={{ borderLeftWidth: 4, borderLeftColor: meta.color }}
        >
            <div className="flex flex-col">
                <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: meta.color }} />
                    <span className="text-xl font-semibold leading-none" style={{ color: meta.color }}>
                        {meta.word}
                    </span>
                </div>
                <span className="mt-1.5 text-xs text-secondary">
                    {summary.workflowCount === 0
                        ? 'No workflow runs in this window'
                        : summary.failingNow > 0
                          ? `${summary.failingNow} of ${summary.workflowCount} workflows failing right now`
                          : summary.flakyNow > 0
                            ? `${summary.flakyNow} flaky · below 90% pass rate`
                            : `All ${summary.workflowCount} workflows healthy`}
                </span>
            </div>

            <div className="flex flex-col border-l border-primary pl-6">
                <span className="text-2xl font-semibold leading-7 tabular-nums">{greenRateLabel}</span>
                <span className="text-xs text-tertiary">green now · {summary.settledWorkflows} settled</span>
            </div>

            <div className="flex-1" />

            <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
                <HealthKpi label="Workflows" value={summary.workflowCount.toLocaleString()} />
                <HealthKpi
                    label="Failing now"
                    value={summary.failingNow.toLocaleString()}
                    danger={summary.failingNow > 0}
                />
                <HealthKpi label="Total runs" value={summary.totalRuns.toLocaleString()} />
                {hasCost && <HealthKpi label="CI cost" value={`≈ ${formatCost(summary.estimatedCostUsd)}`} />}
            </div>
        </div>
    )
}
