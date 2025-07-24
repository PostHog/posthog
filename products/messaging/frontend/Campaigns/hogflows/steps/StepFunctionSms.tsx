import { Node } from '@xyflow/react'

import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'
import { IconTwilio } from 'lib/lemon-ui/icons'
import { StepFunctionConfiguration } from './StepFunction'

export const StepFunctionSms: HogFlowStep<'function_sms'> = {
    type: 'function_sms',
    name: 'SMS',
    description: 'Send an SMS to the user.',
    icon: <IconTwilio />,
    renderNode: (props) => <StepFunctionSmsNode {...props} />,
    renderConfiguration: (node) => <StepFunctionSmsConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'SMS',
                description: '',
                type: 'function_sms',
                on_error: 'continue',
                config: {
                    template_id: 'template-twilio',
                    inputs: {},
                },
            },
        }
    },
}

function StepFunctionSmsNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepFunctionSmsConfiguration(props: {
    node: Node<Extract<HogFlowAction, { type: 'function_sms' }>>
}): JSX.Element {
    return <StepFunctionConfiguration {...props} />
}
