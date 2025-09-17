import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { campaignLogic } from '../../campaignLogic'
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

    const { partialSetCampaignActionConfig } = useActions(campaignLogic)

    return (
        <>
            <StepSchemaErrors />

            <div>
                <LemonLabel>Wait time</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        partialSetCampaignActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>

            <div>
                <LemonLabel>Conditions to wait for</LemonLabel>
                <HogFlowPropertyFilters
                    actionId={action.id}
                    filters={condition.filters ?? {}}
                    setFilters={(filters) => partialSetCampaignActionConfig(action.id, { condition: { filters } })}
                    typeKey="campaign-wait-until-condition"
                />
            </div>
        </>
    )
}
