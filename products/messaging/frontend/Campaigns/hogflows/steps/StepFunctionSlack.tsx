import { Node } from '@xyflow/react'

import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'
import { StepFunctionConfiguration } from './StepFunction'
import { IconSlack } from 'lib/lemon-ui/icons/icons'

export const StepFunctionSlack: HogFlowStep<'function_slack'> = {
    type: 'function_slack',
    name: 'Slack',
    description: 'Send a message to a Slack channel.',
    icon: <IconSlack />,
    renderNode: (props) => <StepFunctionSlackNode {...props} />,
    renderConfiguration: (node) => <StepFunctionSlackConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Slack',
                description: '',
                type: 'function_slack',
                on_error: 'continue',
                config: {
                    template_id: 'template-slack',
                    inputs: {},
                },
            },
        }
    },
}

function StepFunctionSlackNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepFunctionSlackConfiguration(props: {
    node: Node<Extract<HogFlowAction, { type: 'function_slack' }>>
}): JSX.Element {
    return <StepFunctionConfiguration {...props} />
}
