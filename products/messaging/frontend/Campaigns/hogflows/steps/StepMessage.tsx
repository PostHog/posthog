import { IconDecisionTree } from '@posthog/icons'
import { Node } from '@xyflow/react'
import { useActions } from 'kea'
import { NEW_TEMPLATE } from 'products/messaging/frontend/TemplateLibrary/constants'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepMessage: HogFlowStep<'message'> = {
    type: 'message',
    renderNode: (props) => <StepMessageNode {...props} />,
    renderConfiguration: (node) => <StepMessageConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Message',
                description: '',
                type: 'message',
                on_error: 'continue',
                config: {
                    message: { value: NEW_TEMPLATE },
                    channel: 'email',
                },
            },
        }
    },
}

function StepMessageNode({ data }: HogFlowStepNodeProps): JSX.Element {
    // TODO: Use node data to render trigger node
    return <StepView name={data.name} icon={<IconDecisionTree className="text-green-400" />} selected={false} />
}

function StepMessageConfiguration({ node }: { node: Node<Extract<HogFlowAction, { type: 'message' }>> }): JSX.Element {
    const action = node.data
    const { message, channel } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Message</p>
                <p className="mb-0">Send a message to the user.</p>
            </div>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Channel</p>
                <p className="mb-0">Choose which channel to send the message to.</p>
            </div>
        </>
    )
}
