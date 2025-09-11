import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { getHogFlowStep } from '../hogflows/steps/HogFlowSteps'
import { HogFlow } from '../hogflows/types'

// We pull out actions like [Action:action_function_webhook_13ec288f-10af-4e98-abd4-e2828de3305e] and replace them with a link to the action

const ACTION_REGEX = /\[Action:([a-zA-Z0-9_-]+)\]/g

export const renderWorkflowLogMessage = (campaign: HogFlow, message: string): JSX.Element => {
    // TODO: Find the action in the campaign and get the name
    // Modifies the rendered log message to auto-detect action parts and replace them with a link
    const parts = message.split(ACTION_REGEX)
    const elements: (string | JSX.Element)[] = []

    for (let i = 0; i < parts.length; i++) {
        if (i % 2 === 0) {
            // Even indices are regular text parts
            if (parts[i]) {
                elements.push(parts[i])
            }
        } else {
            // Odd indices are action IDs (captured by regex groups)
            const actionId = parts[i]
            const action = campaign.actions.find((action) => action.id === actionId)

            const step = action ? getHogFlowStep(action, {}) : undefined
            const stepName = action?.name

            if (actionId) {
                elements.push(
                    <Link
                        className="rounded p-1 -m-1 bg-border text-bg-primary"
                        to={urls.messagingCampaign(campaign.id, 'workflow') + `?node=${actionId}&mode=logs`}
                    >
                        {step?.icon && <span className="mr-1">{step.icon}</span>}
                        {stepName}
                    </Link>
                )
            }
        }
    }

    return <>{elements}</>
}
