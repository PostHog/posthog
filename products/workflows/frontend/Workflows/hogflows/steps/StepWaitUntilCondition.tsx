import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { IconBolt, IconPerson } from '@posthog/icons'
import { LemonDivider, LemonLabel } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowEventFilters, HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { useDebouncedNameInput } from './utils'

type WaitUntilConditionAction = Extract<HogFlowAction, { type: 'wait_until_condition' }>

export function StepWaitUntilConditionConfiguration({ node }: { node: Node<WaitUntilConditionAction> }): JSX.Element {
    const action = node.data
    const { condition, events, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const { localName: localConditionName, handleNameChange } = useDebouncedNameInput(
        condition ?? {},
        (updatedCondition) => partialSetWorkflowActionConfig(action.id, { condition: updatedCondition })
    )

    // All events live in a single filters object (events[0].filters), matching
    // the trigger's flat event list pattern. The handler iterates over events[].
    const eventFilters = events?.[0]?.filters ?? {}

    return (
        <div className="flex flex-col gap-3">
            <StepSchemaErrors />

            <p className="text-xs text-muted mb-0">
                Wait until a person matches a condition or a specific event fires. The workflow continues on the matched
                path when either happens, or the timeout path if neither does in time.
            </p>

            <div className="flex flex-col gap-2 p-3 rounded border bg-bg-light">
                <div className="flex items-center gap-1">
                    <IconPerson className="text-lg text-muted" />
                    <LemonLabel className="mb-0">Wait for a person property condition</LemonLabel>
                </div>
                <p className="text-xs text-muted mb-0">
                    Re-checks the person's properties on a polling schedule (every 10 minutes).
                </p>
                <LemonInput
                    value={localConditionName || ''}
                    onChange={handleNameChange}
                    placeholder="Condition name (optional)"
                    size="small"
                />
                <HogFlowPropertyFilters
                    filtersKey={`wait-until-condition-${action.id}`}
                    filters={condition?.filters ?? {}}
                    setFilters={(filters) =>
                        partialSetWorkflowActionConfig(action.id, {
                            condition: { ...condition, filters },
                        })
                    }
                    typeKey="workflow-wait-until-condition"
                />
            </div>

            <div className="flex flex-col gap-2 p-3 rounded border bg-bg-light">
                <div className="flex items-center gap-1">
                    <IconBolt className="text-lg text-muted" />
                    <LemonLabel className="mb-0">Wait for an event</LemonLabel>
                </div>
                <p className="text-xs text-muted mb-0">
                    Wakes the workflow in real time when any of these events fire for the person.
                </p>
                <HogFlowEventFilters
                    filtersKey={`wait-until-condition-events-${action.id}`}
                    filters={eventFilters}
                    setFilters={(filters) =>
                        partialSetWorkflowActionConfig(action.id, {
                            events: [{ filters: filters ?? {} }],
                        })
                    }
                    typeKey="workflow-wait-until-condition-events"
                    buttonCopy="Add event"
                />
            </div>

            <LemonDivider className="my-0" />

            <div className="flex flex-col gap-1">
                <LemonLabel>Max time to wait</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        partialSetWorkflowActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>
        </div>
    )
}
