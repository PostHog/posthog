import { IconWebhooks } from '@posthog/icons'

import { StepFunctionConfiguration } from './StepFunction'
import { HogFlowStep } from './types'

export const StepFunctionWebhook: HogFlowStep<'function_webhook'> = {
    type: 'function_webhook',
    name: 'Webhook',
    description: 'Send a webhook to an external service.',
    icon: <IconWebhooks className="text-[#6500ae]" />,
    color: '#6500ae',
    renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Webhook',
                description: '',
                type: 'function_webhook',
                on_error: 'continue',
                config: {
                    template_id: 'template-webhook',
                },
            },
        }
    },
}
