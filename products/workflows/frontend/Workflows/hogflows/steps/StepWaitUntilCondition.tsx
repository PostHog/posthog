import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

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
        <>
            <StepSchemaErrors />

            <p className="text-xs text-muted">
                Wait until a person matches a condition or a specific event fires. The workflow continues on the matched
                path when either happens, or the timeout path if neither does in time.
            </p>

            <div className="flex flex-col gap-1">
                <LemonLabel>Wait for person property condition</LemonLabel>
                <LemonInput
                    value={localConditionName || ''}
                    onChange={handleNameChange}
                    placeholder="If condition matches"
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

            <div className="flex flex-col gap-1">
                <LemonLabel>Wait for events</LemonLabel>
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

            <div className="flex flex-col gap-1">
                <LemonLabel>Max time to wait</LemonLabel>
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
