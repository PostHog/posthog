import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
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
    const { condition, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const { localName: localConditionName, handleNameChange } = useDebouncedNameInput(condition, (updatedCondition) =>
        partialSetWorkflowActionConfig(action.id, { condition: updatedCondition })
    )

    return (
        <>
            <StepSchemaErrors />

            <div className="flex flex-col gap-1">
                <LemonLabel>Wait time</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        partialSetWorkflowActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>

            <div className="flex flex-col gap-1">
                <LemonLabel>Conditions to wait for</LemonLabel>
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
        </>
    )
}
