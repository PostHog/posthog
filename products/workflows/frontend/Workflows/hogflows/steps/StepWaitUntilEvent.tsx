import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonLabel } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'

type WaitUntilEventAction = Extract<HogFlowAction, { type: 'wait_until_event' }>
type EventConfig = WaitUntilEventAction['config']['events'][number]

export function StepWaitUntilEventConfiguration({ node }: { node: Node<WaitUntilEventAction> }): JSX.Element {
    const action = node.data
    const { events, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const setEvents = (nextEvents: EventConfig[]): void => {
        partialSetWorkflowActionConfig(action.id, { events: nextEvents })
    }

    const updateEvent = (index: number, patch: Partial<EventConfig>): void => {
        setEvents(events.map((event, i) => (i === index ? { ...event, ...patch } : event)))
    }

    const addEvent = (): void => {
        setEvents([...events, { filters: {} }])
    }

    const removeEvent = (index: number): void => {
        setEvents(events.filter((_, i) => i !== index))
    }

    return (
        <>
            <StepSchemaErrors />

            <div className="text-xs text-muted">
                Pause until any of the configured events fire for the user, or until the timeout. The matched path is
                taken on event arrival; the timeout path is taken if no event arrives in time. This is different from
                "Wait until condition", which only re-checks person properties on a polling schedule.
            </div>

            {events.map((eventConfig, index) => (
                <div key={index} className="flex flex-col gap-2 p-2 rounded border">
                    <div className="flex justify-between items-center">
                        <LemonLabel>Event {index + 1}</LemonLabel>
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            onClick={() => removeEvent(index)}
                            disabledReason={events.length === 1 ? 'At least one event is required' : undefined}
                        />
                    </div>

                    <HogFlowPropertyFilters
                        filtersKey={`wait-until-event-${action.id}-${index}`}
                        filters={eventConfig.filters ?? {}}
                        setFilters={(filters) => updateEvent(index, { filters: filters ?? {} })}
                        typeKey={`workflow-wait-until-event-${index}`}
                    />

                    <LemonField.Pure label="Subscription name (optional)">
                        <LemonInput
                            value={eventConfig.name ?? ''}
                            onChange={(value) => updateEvent(index, { name: value })}
                            placeholder={`When event #${index + 1} fires`}
                            size="small"
                        />
                    </LemonField.Pure>
                </div>
            ))}

            <LemonButton type="secondary" icon={<IconPlus />} onClick={addEvent}>
                Add event
            </LemonButton>

            <div className="flex flex-col gap-1">
                <LemonLabel>Max time to wait for event</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        partialSetWorkflowActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>
        </>
    )
}
