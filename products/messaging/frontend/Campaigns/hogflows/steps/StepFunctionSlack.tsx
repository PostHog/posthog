import { IconSlack } from 'lib/lemon-ui/icons/icons'

import { StepFunctionConfiguration } from './StepFunction'
import { HogFlowStep } from './types'

export const StepFunctionSlack: HogFlowStep<'function_slack'> = {
    type: 'function_slack',
    name: 'Slack',
    description: 'Send a message to a Slack channel.',
    icon: <IconSlack />,
    color: '#4A154B',
    renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Slack',
                description: '',
                type: 'function_slack',
                on_error: 'continue',
                config: {
                    template_id: 'template-slack',
                },
            },
        }
    },
}
