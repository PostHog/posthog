import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonSelect, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { batchWorkflowJobsLogic } from '../batchWorkflowJobsLogic'
import type { HogFlowBatchJob } from '../hogflows/types'
import { WorkflowOverview } from './WorkflowOverview'

// A waiting or queued run has not started anyone yet, so it has nothing to show.
const NOT_STARTED: HogFlowBatchJob['status'][] = ['waiting', 'queued']

function runLabel(run: HogFlowBatchJob): string {
    // The stored enum value is 'cancelled'; display American spelling.
    const status = run.status === 'cancelled' ? 'canceled' : run.status
    return `${dayjs(run.created_at).format('MMM D, YYYY HH:mm')} · ${status}`
}

export function WorkflowBatchOverview({ id }: { id: string }): JSX.Element {
    const { batchWorkflowJobs, batchWorkflowJobsLoading } = useValues(batchWorkflowJobsLogic({ id }))
    const runs = useMemo(
        () =>
            (batchWorkflowJobs ?? [])
                .filter((run) => !NOT_STARTED.includes(run.status))
                .sort((a, b) => dayjs(b.created_at).valueOf() - dayjs(a.created_at).valueOf()),
        [batchWorkflowJobs]
    )
    const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

    if (batchWorkflowJobs === null || (batchWorkflowJobsLoading && runs.length === 0)) {
        return (
            <div className="flex justify-center">
                <Spinner size="medium" />
            </div>
        )
    }

    if (runs.length === 0) {
        return (
            <div
                className="flex flex-col items-center rounded bg-surface-primary px-4 py-8 text-center"
                data-attr="workflow-batch-overview-empty"
            >
                <h2 className="text-xl leading-tight">This workflow hasn't run yet</h2>
                <p className="text-sm text-tertiary">Once a run starts, its results show here.</p>
            </div>
        )
    }

    const runIndex = Math.max(
        0,
        runs.findIndex((run) => run.id === selectedRunId)
    )
    const run = runs[runIndex]
    const previousRun = runs[runIndex + 1] ?? null

    return (
        <WorkflowOverview
            key={run.id}
            id={id}
            run={run}
            previousRun={previousRun}
            controls={
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-muted" data-attr="workflow-batch-overview-comparison">
                        {previousRun
                            ? `Compared with the run on ${dayjs(previousRun.created_at).format('MMM D, HH:mm')}`
                            : 'First run, so there is nothing to compare with'}
                    </span>
                    <LemonSelect
                        size="small"
                        value={run.id}
                        onChange={(value) => setSelectedRunId(value)}
                        options={runs.map((r) => ({ value: r.id, label: runLabel(r) }))}
                        data-attr="workflow-batch-overview-run-picker"
                    />
                </div>
            }
        />
    )
}
