import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { workflowLogic } from '../../../workflowLogic'
import { HogFlowSchedule } from '../../types'
import { buildSummary, isOneTimeSchedule, parseRRuleToState } from './rrule-helpers'

function scheduleSummary(schedule: HogFlowSchedule): string {
    if (isOneTimeSchedule(schedule.rrule)) {
        return 'Runs once'
    }
    return buildSummary(parseRRuleToState(schedule.rrule), schedule.starts_at, schedule.timezone)
}

function ScheduleStateTag({ status }: { status?: string }): JSX.Element | null {
    if (status === 'completed') {
        return (
            <LemonTag type="default" size="small">
                Completed
            </LemonTag>
        )
    }
    if (status === 'paused') {
        return (
            <LemonTag type="warning" size="small">
                Paused
            </LemonTag>
        )
    }
    return null
}

function ScheduleRow({ schedule, editedHere }: { schedule: HogFlowSchedule; editedHere: boolean }): JSX.Element {
    const { deleteSchedule } = useActions(workflowLogic)

    return (
        <div className="flex items-center gap-2 py-1.5 px-2 border-b last:border-b-0">
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="truncate">{scheduleSummary(schedule)}</span>
                    <ScheduleStateTag status={schedule.status} />
                    {editedHere && (
                        <LemonTag type="highlight" size="small">
                            Editing below
                        </LemonTag>
                    )}
                </div>
                <div className="text-xs text-muted">
                    {schedule.timezone ?? 'UTC'}
                    {schedule.next_run_at
                        ? ` · next run ${dayjs(schedule.next_run_at)
                              .tz(schedule.timezone ?? 'UTC')
                              .format('D MMM, HH:mm')}`
                        : ''}
                </div>
            </div>
            <LemonButton
                icon={<IconTrash />}
                size="small"
                status="danger"
                tooltip="Remove this schedule"
                data-attr="remove-workflow-schedule"
                onClick={() =>
                    LemonDialog.open({
                        title: 'Remove this schedule?',
                        description: `${scheduleSummary(schedule)}. The workflow stops running on it. Any other schedules keep going.`,
                        primaryButton: {
                            children: 'Remove',
                            status: 'danger',
                            onClick: () => deleteSchedule(schedule.id),
                        },
                        secondaryButton: { children: 'Cancel' },
                    })
                }
            />
        </div>
    )
}

// Every surface used to read schedules[0], so a workflow that holds more than one showed a single
// schedule and silently ran the rest. Listing them is what lets an author find and remove one.
export function ScheduleList(): JSX.Element | null {
    const { schedules, currentSchedule } = useValues(workflowLogic)

    if (schedules.length < 2) {
        return null
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
                <span className="font-semibold text-sm">This workflow has {schedules.length} schedules</span>
            </div>
            <p className="text-xs text-muted mb-0">
                They all run. Remove any you did not mean to add. Only the one marked below is edited here.
            </p>
            <div className="border rounded bg-surface-primary">
                {schedules.map((schedule) => (
                    <ScheduleRow
                        key={schedule.id}
                        schedule={schedule}
                        editedHere={schedule.id === currentSchedule?.id}
                    />
                ))}
            </div>
        </div>
    )
}
