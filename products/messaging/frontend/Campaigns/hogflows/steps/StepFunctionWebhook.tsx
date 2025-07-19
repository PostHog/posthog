import { IconWebhooks } from '@posthog/icons'
import { Node } from '@xyflow/react'

import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'
import { StepFunctionConfiguration } from './StepFunction'

export const StepFunctionWebhook: HogFlowStep<'function_webhook'> = {
    type: 'function_webhook',
    name: 'Webhook',
    description: 'Send a webhook to an external service.',
    icon: <IconWebhooks />,
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
