import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { HogFlowFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'

export function StepWaitUntilConditionConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'wait_until_condition' }>>
}): JSX.Element {
    const action = node.data
    const { condition, max_wait_duration } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    return (
        <>
            <div>
                <LemonLabel>Wait time</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        setCampaignActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>

            <div>
                <LemonLabel>Conditions to wait for</LemonLabel>
                <HogFlowFilters
                    filters={condition.filters ?? {}}
                    setFilters={(filters) => setCampaignActionConfig(action.id, { condition: { filters } })}
                    typeKey="campaign-wait-until-condition"
                />
            </div>
        </>
    )
}
