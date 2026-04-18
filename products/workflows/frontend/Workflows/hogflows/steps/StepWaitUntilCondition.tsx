import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonDivider, LemonLabel } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowEventFilters, HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { useDebouncedNameInput } from './utils'

export function StepWaitUntilConditionConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'wait_until_condition' }>>
}): JSX.Element {
    const action = node.data
    const { condition, events, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const { localName: localConditionName, handleNameChange } = useDebouncedNameInput(condition, (updatedCondition) =>
        partialSetWorkflowActionConfig(action.id, { condition: updatedCondition })
    )

    const eventFilters = events?.[0]?.filters ?? {}

    return (
        <>
            <StepSchemaErrors />

            <div className="flex flex-col gap-1">
                <LemonLabel>Events to wait for</LemonLabel>
                <p className="text-xs text-muted">
                    The workflow continues on the matched path when any of these events fire.
                </p>
                <HogFlowEventFilters
                    filtersKey={`wait-until-events-${action.id}`}
                    filters={eventFilters}
                    setFilters={(newFilters) =>
                        partialSetWorkflowActionConfig(action.id, {
                            events: [{ filters: newFilters ?? {} }],
                        })
                    }
                    typeKey="workflow-wait-until-event"
                    buttonCopy="Add event"
                />
            </div>

            <LemonDivider className="my-2" />

            <div className="flex flex-col gap-1">
                <LemonLabel>Property conditions</LemonLabel>
                <LemonInput
                    value={localConditionName || ''}
                    onChange={handleNameChange}
                    placeholder="If condition matches"
                    size="small"
                />
                <HogFlowPropertyFilters
                    filtersKey={`wait-until-condition-${action.id}`}
                    filters={condition.filters ?? {}}
                    setFilters={(filters) =>
                        partialSetWorkflowActionConfig(action.id, { condition: { ...condition, filters } })
                    }
                    typeKey="workflow-wait-until-condition"
                />
            </div>

            <LemonDivider className="my-2" />

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
