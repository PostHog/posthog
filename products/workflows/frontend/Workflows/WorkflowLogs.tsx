import { useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonCollapse, LemonDivider, ProfilePicture, Spinner, Tooltip } from '@posthog/lemon-ui'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { WarningHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
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

function BatchRunHeader({ job }: { job: any }): JSX.Element {
    return (
        <div className="flex gap-2 w-full justify-between">
            <strong>{job.id}</strong>
            <div className="flex items-center gap-2">
                {job.scheduled_at && (
                    <>
                        <IconClock className="text-lg" /> <TZLabel time={job.scheduled_at} />
                        <LemonDivider vertical className="h-full" />
                    </>
                )}
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

function BatchRunInfo({ job }: { job: any }): JSX.Element {
    const { workflow } = useValues(workflowLogic({ id: job.hog_flow_id }))

    const isFutureJob = dayjs(job.scheduled_at).isAfter(dayjs())

    const logsSection = isFutureJob ? (
        <div className="flex flex-col w-full bg-surface-primary rounded py-8 items-center text-center">
            <WarningHog width="w-full" height="80" className="mb-4" />
            <h2 className="text-xl leading-tight">This job hasn't started yet</h2>
            <p className="text-sm text-balance text-tertiary">
                Once the job starts executing, logs will start to appear here.
            </p>
        </div>
    ) : (
        <LogsViewer
            sourceType="hog_flow"
            sourceId={job.id}
            instanceLabel="workflow job"
            renderMessage={(m) => renderWorkflowLogMessage(workflow, m)}
        />
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-2 items-start">
                <span className="text-muted">Filters</span>
                <PropertyFiltersDisplay filters={job.filters.properties} />
            </div>
            {logsSection}
        </div>
    )
}

function WorkflowBatchRunLogs({ id }: WorkflowLogsProps): JSX.Element {
    const { futureJobs, pastJobs, batchWorkflowJobsLoading } = useValues(batchWorkflowJobsLogic({ id }))

    if (batchWorkflowJobsLoading) {
        return (
            <div className="flex justify-center">
                <Spinner className="text-xl" />
            </div>
        )
    }

    if (!futureJobs.length && !pastJobs.length) {
        return (
            <div className="flex flex-col bg-surface-primary rounded px-4 py-8 items-center text-center mx-auto">
                <WarningHog width="100" height="100" className="mb-4" />
                <h2 className="text-xl leading-tight">No batch workflow jobs have been run yet</h2>
                <p className="text-sm text-balance text-tertiary">
                    Once a batch workflow job is triggered, execution logs will appear here.
                </p>
            </div>
        )
    }

    const pastJobsSection = (
        <LemonCollapse
            panels={(pastJobs || []).map((job) => ({
                key: job.id,
                header: <BatchRunHeader job={job} />,
                content: <BatchRunInfo job={job} />,
            }))}
        />
    )

    if (futureJobs.length === 0) {
        // If no past jobs, just render past jobs directly
        return pastJobsSection
    }

    const futureJobsSection = (
        <LemonCollapse
            panels={futureJobs.map((job) => ({
                key: job.id,
                header: <BatchRunHeader job={job} />,
                content: <BatchRunInfo job={job} />,
            }))}
        />
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
