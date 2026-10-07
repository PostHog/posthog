import { isEmailAction } from './Workflows/hogflows/steps/types'
import { HogFlowAction } from './Workflows/hogflows/types'

// One visible recipient and no cc/bcc is what keeps a real test send away from the workflow's audience.
export function withTestEmailRecipient(action: HogFlowAction, recipientEmail: string): HogFlowAction {
    if (!isEmailAction(action)) {
        return action
    }
    const email = action.config.inputs?.email
    return {
        ...action,
        config: {
            ...action.config,
            inputs: {
                ...action.config.inputs,
                email: {
                    ...email,
                    value: { ...email?.value, to: { email: recipientEmail, name: '' }, cc: '', bcc: '' },
                },
            },
        },
    }
}
