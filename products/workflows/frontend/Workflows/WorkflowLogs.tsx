import { useValues } from 'kea'
import { type ReactNode, useMemo } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonCollapse, LemonDivider, ProfilePicture, Spinner, Tooltip } from '@posthog/lemon-ui'

import { ListHog } from 'lib/components/hedgehogs'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { OccurrencesList } from './hogflows/steps/components/OccurrencesList'
import {
    buildSummary,
    computePreviewOccurrences,
    fakeUtcToReal,
    isOneTimeSchedule,
    parseRRuleToState,
} from './hogflows/steps/components/rrule-helpers'
import { HogFlowBatchJob } from './hogflows/types'
import { renderWorkflowLogMessage } from './logs/log-utils'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

export type WorkflowLogsProps = {
    id: string
}

function WorkflowRunLogs(props: WorkflowLogsProps): JSX.Element {
    const { workflow } = useValues(workflowLogic)

    return (
        <LogsViewer
            sourceType="hog_flow"
            sourceId={props.id!}
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
                <TZLabel title="Created at" time={job.created_at} />
                <LemonDivider vertical className="h-full" />

                {job.created_by ? (
                    <Tooltip title={`Triggered by ${job.created_by.email}`}>
                        <div>
                            <ProfilePicture user={{ email: job.created_by.email }} showName size="sm" />
                        </div>
                    </Tooltip>
                ) : (
                    <span className="text-muted text-sm">Scheduled run</span>
                )}
            </div>
        </div>
    )
}

function BatchRunInfo({ job }: { job: HogFlowBatchJob }): JSX.Element {
    const { workflow } = useValues(workflowLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-2 items-start w-full">
                <span className="text-muted">Job filters</span>
                <PropertyFiltersDisplay
                    filters={Array.isArray(job.filters?.properties) ? job.filters.properties : []}
                />
            </div>
            <span className="text-muted">Logs</span>
            <LogsViewer
                sourceType="hog_flow"
                sourceId={job.id}
                groupByInstanceId
                instanceLabel="workflow job"
                renderMessage={(m) => renderWorkflowLogMessage(workflow, m)}
            />
        </div>
    )
}

function UpcomingOccurrences(): JSX.Element | null {
    const { currentSchedule } = useValues(workflowLogic)

    const scheduleState = useMemo(() => {
        if (!currentSchedule?.rrule || isOneTimeSchedule(currentSchedule.rrule)) {
            return null
        }
        return parseRRuleToState(currentSchedule.rrule)
    }, [currentSchedule])

    const occurrences = useMemo(() => {
        if (!scheduleState || !currentSchedule) {
            return []
        }
        return computePreviewOccurrences(scheduleState, currentSchedule.starts_at, currentSchedule.timezone)
    }, [scheduleState, currentSchedule])

    const summary = scheduleState ? buildSummary(scheduleState, currentSchedule?.starts_at ?? null) : null
    const timezone = currentSchedule?.timezone
    const hasFutureOccurrences = occurrences.some((d) => fakeUtcToReal(d, timezone).isAfter(dayjs()))

    if (!hasFutureOccurrences) {
        return null
    }

    return (
        <div>
            <SectionHeading>Upcoming</SectionHeading>
            <div className="border rounded-lg p-3 bg-bg-light max-w-xl">
                {summary && (
                    <div className="flex items-center gap-2 mb-3">
                        <IconClock className="text-muted shrink-0" />
                        <span className="text-sm">{summary}</span>
                    </div>
                )}
                <div className="text-xs text-muted mb-2">
                    <span className="font-semibold uppercase tracking-wide">Next occurrences</span>
                    {timezone ? ` in ${timezone}` : ''}
                </div>
                <div className="space-y-1.5">
                    <OccurrencesList
                        occurrences={occurrences}
                        isFinite={scheduleState?.endType !== 'never'}
                        timezone={timezone}
                        showRelativeTime
                    />
                </div>
            </div>
        </div>
    )
}

function SectionHeading({ children }: { children: ReactNode }): JSX.Element {
    return <h3 className="text-xs font-semibold uppercase tracking-wide text-muted mb-1">{children}</h3>
}

function WorkflowBatchRunLogs(props: WorkflowLogicProps): JSX.Element {
    const { jobs, batchWorkflowJobsLoading } = useValues(batchWorkflowJobsLogic(props))
    const { currentSchedule } = useValues(workflowLogic)
    const hasSchedule = !!currentSchedule?.rrule && !isOneTimeSchedule(currentSchedule.rrule)

    if (batchWorkflowJobsLoading) {
        return (
            <div className="flex justify-center">
                <Spinner size="medium" />
            </div>
        )
    }

    if (!jobs.length) {
        return (
            <div className="flex flex-col gap-4">
                <UpcomingOccurrences />
                <div className="flex flex-col bg-surface-primary rounded px-4 py-8 items-center text-center mx-auto">
                    <ListHog width="100" height="100" className="mb-4" />
                    <h2 className="text-xl leading-tight">No batch workflow jobs have been run yet</h2>
                    <p className="text-sm text-balance text-tertiary">
                        Once a batch workflow job is triggered, execution logs will appear here.
                    </p>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <UpcomingOccurrences />
            <div>
                {hasSchedule && <SectionHeading>Past invocations</SectionHeading>}
                <LemonCollapse
                    panels={jobs.map((job) => ({
                        key: job.id,
                        header: <BatchRunHeader job={job} />,
                        content: <BatchRunInfo job={job} />,
                    }))}
                />
            </div>
        </div>
    )
}

export function WorkflowLogs({ id }: WorkflowLogsProps): JSX.Element {
    const { workflow } = useValues(workflowLogic)

    return (
        <div data-attr="workflow-logs">
            {workflow?.trigger?.type === 'batch' ? <WorkflowBatchRunLogs id={id} /> : <WorkflowRunLogs id={id} />}
        </div>
    )
}
