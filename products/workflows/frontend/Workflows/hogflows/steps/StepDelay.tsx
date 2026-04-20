import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { stepDelayLogic } from './stepDelayLogic'

export function StepDelayConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'delay' }>>
}): JSX.Element {
    const action = node.data
    const { delay_duration } = action.config

    const { logicProps } = useValues(workflowLogic)
    const { setDelayWorkflowActionConfig } = useActions(stepDelayLogic({ workflowLogicProps: logicProps }))

    return (
        <>
            <StepSchemaErrors />

            <p className="mb-0">Wait for a specified duration.</p>
            <HogFlowDuration
                value={delay_duration}
                onChange={(value) => {
                    setDelayWorkflowActionConfig(action.id, { delay_duration: value })
                }}
            />
        </>
    )
}
