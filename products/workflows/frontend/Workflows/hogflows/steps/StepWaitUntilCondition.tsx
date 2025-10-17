import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'

export function StepWaitUntilConditionConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'wait_until_condition' }>>
}): JSX.Element {
    const action = node.data
    const { condition, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    return (
        <>
            <StepSchemaErrors />

            <div>
                <LemonLabel>Wait time</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        partialSetWorkflowActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>

            <div>
                <LemonLabel>Conditions to wait for</LemonLabel>
                <HogFlowPropertyFilters
                    actionId={action.id}
                    filters={condition.filters ?? {}}
                    setFilters={(filters) => partialSetWorkflowActionConfig(action.id, { condition: { filters } })}
                    typeKey="workflow-wait-until-condition"
                />
            </div>
        </>
    )
}
