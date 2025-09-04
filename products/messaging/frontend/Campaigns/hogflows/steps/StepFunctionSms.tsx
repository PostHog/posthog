import { IconTwilio } from 'lib/lemon-ui/icons'

import { StepFunctionConfiguration } from './StepFunction'
import { HogFlowStep } from './types'

export const StepFunctionSms: HogFlowStep<'function_sms'> = {
    type: 'function_sms',
    name: 'SMS',
    description: 'Send an SMS to the user.',
    icon: <IconTwilio className="text-[#f22f46]" />,
    color: '#f22f46',
    renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'SMS',
                description: '',
                type: 'function_sms',
                on_error: 'continue',
                config: {
                    template_id: 'template-twilio',
                },
            },
        }
    },
}
