import { IconDecisionTree } from '@posthog/icons'
import { Node } from '@xyflow/react'
import { NEW_TEMPLATE } from 'products/messaging/frontend/TemplateLibrary/constants'

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

function StepMessageConfiguration({}: { node: Node<Extract<HogFlowAction, { type: 'message' }>> }): JSX.Element {
    return (
        <>
            <p>Coming soon!</p>
        </>
    )
}
