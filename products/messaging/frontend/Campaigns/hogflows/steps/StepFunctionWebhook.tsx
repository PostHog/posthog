import { Node } from '@xyflow/react'

import { IconWebhooks } from '@posthog/icons'

import { HogFlowAction } from '../types'
import { StepFunctionConfiguration } from './StepFunction'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepFunctionWebhook: HogFlowStep<'function_webhook'> = {
    type: 'function_webhook',
    name: 'Webhook',
    description: 'Send a webhook to an external service.',
    icon: <IconWebhooks className="text-[#6500ae]" />,
    color: '#6500ae',
    renderNode: (props) => <StepFunctionWebhookNode {...props} />,
    renderConfiguration: (node) => <StepFunctionWebhookConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Webhook',
                description: '',
                type: 'function_webhook',
                on_error: 'continue',
                config: {
                    template_id: 'template-webhook',
                    inputs: {},
                },
            },
        }
    },
}

function StepFunctionWebhookNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepFunctionWebhookConfiguration(props: {
    node: Node<Extract<HogFlowAction, { type: 'function_webhook' }>>
}): JSX.Element {
    return <StepFunctionConfiguration {...props} />
}
