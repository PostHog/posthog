import { useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonCollapse, LemonDivider, ProfilePicture, Spinner, Tooltip } from '@posthog/lemon-ui'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { ListHog, SleepingHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { HogFlowBatchJob } from './hogflows/types'
import { renderWorkflowLogMessage } from './logs/log-utils'
import { workflowLogic } from './workflowLogic'

export type WorkflowLogsProps = {
    id: string
}

function WorkflowRunLogs({ id }: WorkflowLogsProps): JSX.Element {
    const { workflow } = useValues(workflowLogic({ id }))

    return (
        <LogsViewer
            sourceType="hog_flow"
            sourceId={id}
            instanceLabel="workflow run"
            renderMessage={(m) => renderWorkflowLogMessage(workflow, m)}
        />
    )
}

function BatchRunHeader({ job }: { job: HogFlowBatchJob }): JSX.Element {
    return (
        <div className="flex gap-2 w-full justify-between">
            <strong>{job.id}</strong>
            <div className="flex items-center gap-2">
                {job.scheduled_at && (
                    <Tooltip title="This job was scheduled to run in advance" placement="left">
                        <div className="flex items-center gap-2 text-muted">
                            <IconClock className="text-lg" />
                            <TZLabel title="Scheduled at" time={job.scheduled_at} />
                            {' ⋅ '}
                        </div>
                    </Tooltip>
                )}
                <TZLabel title="Created at" time={job.created_at} />
                <LemonDivider vertical className="h-full" />

                <Tooltip
                    title={`${job.scheduled_at ? 'Scheduled' : 'Triggered'} by ${job.created_by?.email || 'unknown user'}`}
                >
                    <div>
                        <ProfilePicture
                            user={{
                                email: job.created_by?.email || '',
                            }}
                            showName
                            size="sm"
                        />
                    </div>
                </Tooltip>
            </div>
        </div>
    )
}

function BatchRunInfo({ job }: { job: HogFlowBatchJob }): JSX.Element {
    const { workflow } = useValues(workflowLogic({ id: job.hog_flow_id }))

    const isFutureJob = job.scheduled_at && dayjs(job.scheduled_at).isAfter(dayjs())

    const logsSection = isFutureJob ? (
        <div className="flex flex-col w-full bg-surface-primary rounded py-8 items-center text-center">
            <SleepingHog width="100" height="100" className="mb-4" />
            <h2 className="text-xl leading-tight">This job hasn't started yet</h2>
            <p className="text-sm text-balance text-tertiary">Once the job starts executing, logs will appear here.</p>
        </div>
    ) : (
        <LogsViewer
            sourceType="hog_flow"
            sourceId={job.id}
            groupByInstanceId
            instanceLabel="workflow job"
            renderMessage={(m) => renderWorkflowLogMessage(workflow, m)}
        />
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-2 items-start">
                <span className="text-muted">Job filters</span>
                <PropertyFiltersDisplay filters={job.filters?.properties || []} />
            </div>
            <span className="text-muted">Logs</span>
            {logsSection}
        </div>
    )
}

function WorkflowBatchRunLogs({ id }: WorkflowLogsProps): JSX.Element {
    const { futureJobs, pastJobs, batchWorkflowJobsLoading } = useValues(batchWorkflowJobsLogic({ id }))

    if (batchWorkflowJobsLoading) {
        return (
            <div className="flex justify-center">
                <Spinner size="medium" />
            </div>
        )
    }

    if (!futureJobs.length && !pastJobs.length) {
        return (
            <div className="flex flex-col bg-surface-primary rounded px-4 py-8 items-center text-center mx-auto">
                <ListHog width="100" height="100" className="mb-4" />
                <h2 className="text-xl leading-tight">No batch workflow jobs have been run yet</h2>
                <p className="text-sm text-balance text-tertiary">
                    Once a batch workflow job is triggered, execution logs will appear here.
                </p>
            </div>
        )
    }

    const futureJobsSection = futureJobs.length ? (
        <LemonCollapse
            panels={futureJobs.map((job) => ({
                key: job.id,
                header: <BatchRunHeader job={job} />,
                content: <BatchRunInfo job={job} />,
            }))}
        />
    ) : (
        <div className="border rounded bg-surface-primary p-2 text-muted">No scheduled jobs.</div>
    )

    const pastJobsSection = pastJobs.length ? (
        <LemonCollapse
            panels={pastJobs.map((job) => ({
                key: job.id,
                header: <BatchRunHeader job={job} />,
                content: <BatchRunInfo job={job} />,
            }))}
        />
    ) : (
        <div className="border rounded bg-surface-primary p-2 text-muted">No past jobs.</div>
    )

    return (
        <div className="flex flex-col gap-2">
            <h2 className="text-lg font-semibold">Scheduled jobs</h2>
            {futureJobsSection}
            <h2 className="text-lg font-semibold mt-4">Past jobs</h2>
            {pastJobsSection}
        </div>
    )
}

export function WorkflowLogs({ id }: WorkflowLogsProps): JSX.Element {
    const { workflow } = useValues(workflowLogic({ id }))

    return workflow?.trigger?.type === 'batch' ? <WorkflowBatchRunLogs id={id} /> : <WorkflowRunLogs id={id} />
}
