import { Node } from '@xyflow/react'

import { IconLetter } from '@posthog/icons'

import { HogFlowAction } from '../types'
import { StepFunctionConfiguration } from './StepFunction'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepFunctionEmail: HogFlowStep<'function_email'> = {
    type: 'function_email',
    name: 'Email',
    description: 'Send an email to the user.',
    icon: <IconLetter className="text-[#005841]" />,
    color: '#005841',
    renderNode: (props) => <StepFunctionEmailNode {...props} />,
    renderConfiguration: (node) => <StepFunctionEmailConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Email',
                description: '',
                type: 'function_email',
                on_error: 'continue',
                config: {
                    template_id: 'template-email',
                    inputs: {},
                },
            },
        }
    },
}

function StepFunctionEmailNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepFunctionEmailConfiguration(props: {
    node: Node<Extract<HogFlowAction, { type: 'function_email' }>>
}): JSX.Element {
    return <StepFunctionConfiguration {...props} />
}
