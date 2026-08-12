import { useValues } from 'kea'
import { type ReactNode, useMemo } from 'react'

import * as greekPng from '@posthog/brand/hoggies/png/greek'
import { IconClock } from '@posthog/icons'
import { LemonCollapse, LemonDivider, LemonTag, ProfilePicture, Spinner, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { HogInvocations } from 'scenes/hog-functions/invocations/HogInvocations'

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
import { workflowLogic } from './workflowLogic'

const HedgehogGreek = pngHoggie(greekPng)

const STATUS_TAG_TYPE: Record<HogFlowBatchJob['status'], 'success' | 'danger' | 'warning' | 'default'> = {
    completed: 'success',
    failed: 'danger',
    cancelled: 'default',
    waiting: 'warning',
    queued: 'warning',
    active: 'warning',
}

function SectionHeading({ children }: { children: ReactNode }): JSX.Element {
    return <h3 className="text-xs font-semibold uppercase tracking-wide text-muted mb-1">{children}</h3>
}

function BatchRunHeader({ job }: { job: HogFlowBatchJob }): JSX.Element {
    return (
        <div className="flex gap-2 w-full justify-between">
            <div className="flex items-center gap-2 min-w-0">
                <strong className="truncate">{job.id}</strong>
                <LemonTag type={STATUS_TAG_TYPE[job.status] ?? 'default'}>{job.status}</LemonTag>
            </div>
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

function BatchRunInvocations({ job, hogFlowId }: { job: HogFlowBatchJob; hogFlowId: string }): JSX.Element {
    const { workflow } = useValues(workflowLogic)

    // Broadcasts can be older than the flat list's 24h default, so anchor the window
    // just before the job was created to keep this run's invocations in range.
    const defaultDateFrom = dayjs(job.created_at).subtract(1, 'day').format('YYYY-MM-DD')

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2 items-start w-full">
                <span className="text-muted">Job filters</span>
                <PropertyFiltersDisplay
                    filters={Array.isArray(job.filters?.properties) ? job.filters.properties : []}
                />
            </div>
            <div className="flex flex-col gap-2">
                <HogInvocations
                    id={hogFlowId}
                    functionKind="hog_flow"
                    parentRunId={job.id}
                    defaultDateFrom={defaultDateFrom}
                    compact
                    renderLogMessage={workflow ? (m) => renderWorkflowLogMessage(workflow, m) : undefined}
                />
            </div>
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

/**
 * Batch-triggered workflows fan out one child invocation per person. The flat invocations
 * table can't tell which broadcast a run belongs to, so here we group runs by batch job —
 * each job expands to its own scoped invocations table — and preview the schedule's upcoming
 * occurrences. Mirrors the batch grouping the standalone Logs tab used to show.
 */
export function WorkflowBatchInvocations({ id }: { id: string }): JSX.Element {
    const { jobs, batchWorkflowJobsLoading } = useValues(batchWorkflowJobsLogic({ id }))
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
                    <HedgehogGreek width="100" height="100" className="mb-4" />
                    <h2 className="text-xl leading-tight">No batch workflow jobs have been run yet</h2>
                    <p className="text-sm text-balance text-tertiary">
                        Once a batch workflow job is triggered, its invocations will appear here.
                    </p>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4" data-attr="workflow-batch-invocations">
            <UpcomingOccurrences />
            <div>
                {hasSchedule && <SectionHeading>Past invocations</SectionHeading>}
                <LemonCollapse
                    panels={jobs.map((job) => ({
                        key: job.id,
                        header: <BatchRunHeader job={job} />,
                        content: <BatchRunInvocations job={job} hogFlowId={id} />,
                    }))}
                />
            </div>
        </div>
    )
}
