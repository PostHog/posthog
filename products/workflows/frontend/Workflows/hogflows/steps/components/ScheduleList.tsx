import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { workflowLogic } from '../../../workflowLogic'
import { HogFlowSchedule } from '../../types'
import { summarizeSchedule } from './rrule-helpers'

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

function ScheduleRow({ schedule, editing }: { schedule: HogFlowSchedule; editing: boolean }): JSX.Element {
    const { deleteSchedule, selectSchedule } = useActions(workflowLogic)
    const { pendingSchedule } = useValues(workflowLogic)

    // Picking another row rebaselines the picker from the saved schedule, so an unsaved change to
    // the current one would go without the author noticing.
    const pickThisRow = (): void => {
        if (editing) {
            return
        }
        if (pendingSchedule !== false) {
            LemonDialog.open({
                title: 'Discard your unsaved schedule change?',
                description: 'You changed the schedule you are editing and have not saved it yet.',
                primaryButton: {
                    children: 'Discard and switch',
                    status: 'danger',
                    onClick: () => selectSchedule(schedule),
                },
                secondaryButton: { children: 'Keep editing' },
            })
            return
        }
        selectSchedule(schedule)
    }

    const summary = summarizeSchedule(schedule.rrule, schedule.starts_at, schedule.timezone)

    return (
        <div className="flex items-center gap-1 p-1">
            <LemonButton
                fullWidth
                className="flex-1 min-w-0"
                active={editing}
                onClick={pickThisRow}
                data-attr="workflow-schedule-row"
            >
                <div className="flex-1 min-w-0 py-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="truncate">{summary}</span>
                        <ScheduleStateTag status={schedule.status} />
                        {editing && (
                            <LemonTag type="highlight" size="small">
                                Editing below
                            </LemonTag>
                        )}
                    </div>
                    <div className="text-xs text-muted font-normal">
                        {schedule.timezone ?? 'UTC'}
                        {schedule.next_run_at
                            ? ` · next run ${dayjs(schedule.next_run_at)
                                  .tz(schedule.timezone ?? 'UTC')
                                  .format('D MMM, HH:mm')}`
                            : ''}
                    </div>
                </div>
            </LemonButton>
            <LemonButton
                icon={<IconTrash />}
                size="small"
                status="danger"
                tooltip="Remove this schedule"
                data-attr="remove-workflow-schedule"
                onClick={() =>
                    LemonDialog.open({
                        title: 'Remove this schedule?',
                        description: `${summary}. The workflow stops running on it. Any other schedules keep going.`,
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
// schedule and silently ran the rest. Listing them is what lets an author pick, add or remove one.
export function ScheduleList(): JSX.Element | null {
    const { schedules, currentSchedule, logicProps, addingSchedule } = useValues(workflowLogic)
    const { addSchedule } = useActions(workflowLogic)

    if (schedules.length === 0) {
        return null
    }

    const addButton = (
        <LemonButton
            icon={<IconPlus />}
            size="small"
            type="secondary"
            data-attr="add-workflow-schedule"
            loading={addingSchedule}
            disabledReason={
                logicProps.id === 'new' ? 'Save the workflow first' : addingSchedule ? 'Adding a schedule' : undefined
            }
            onClick={() => addSchedule()}
        >
            Add schedule
        </LemonButton>
    )

    if (schedules.length === 1) {
        return <div className="flex">{addButton}</div>
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-sm">This workflow has {schedules.length} schedules</span>
                {addButton}
            </div>
            <p className="text-xs text-muted mb-0">
                They all run. Pick one to edit it below, or remove any you did not mean to add.
            </p>
            <div className="border rounded bg-surface-primary divide-y">
                {schedules.map((schedule) => (
                    <ScheduleRow key={schedule.id} schedule={schedule} editing={schedule.id === currentSchedule?.id} />
                ))}
            </div>
        </div>
    )
}
