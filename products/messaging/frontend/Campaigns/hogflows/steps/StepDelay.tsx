import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { campaignLogic } from '../../campaignLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'

export function StepDelayConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'delay' }>>
}): JSX.Element {
    const action = node.data
    const { delay_duration } = action.config

    const { setCampaignActionConfig } = useActions(campaignLogic)

    return (
        <>
            <StepSchemaErrors />

            <p className="mb-0">Wait for a specified duration.</p>
            <HogFlowDuration
                value={delay_duration}
                onChange={(value) => setCampaignActionConfig(action.id, { delay_duration: value })}
            />
        </>
    )
}
