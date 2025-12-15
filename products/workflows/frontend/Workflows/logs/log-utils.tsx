import { Link, ProfilePicture } from '@posthog/lemon-ui'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { getHogFlowStep } from '../hogflows/steps/HogFlowSteps'
import { HogFlow } from '../hogflows/types'

// We pull out actions like [Action:action_function_webhook_13ec288f-10af-4e98-abd4-e2828de3305e] and replace them with a link to the action

const RICH_LOG_REGEX = /(\[[a-zA-Z0-9_-]+:.*?\])/

const ACTION_REGEX = /\[Action:([a-zA-Z0-9_-]+)\]/
const PERSON_REGEX = /\[Person:([a-zA-Z0-9_-]+)\|(.*?)\]/
const ACTOR_REGEX = /\[Actor:(.*?)\]/

export const renderWorkflowLogMessage = (workflow: HogFlow, message: string): JSX.Element => {
    // Modifies the rendered log message to auto-detect action or person parts and replace them with a link
    const parts = message.split(RICH_LOG_REGEX)
    const elements: (string | JSX.Element)[] = []

    for (const part of parts) {
        const matchesActionRegex = ACTION_REGEX.exec(part)

        if (matchesActionRegex) {
            const actionId = matchesActionRegex[1]
            const action = workflow.actions.find((action) => action.id === actionId)

            const step = action ? getHogFlowStep(action, {}) : undefined
            const stepName = action?.name

            elements.push(
                <Link
                    key={part}
                    className="rounded p-1 -m-1 bg-border text-bg-primary"
                    to={urls.workflow(workflow.id, 'workflow') + `?node=${actionId}&mode=logs`}
                >
                    {step?.icon && <span className="mr-1">{step.icon}</span>}
                    {stepName}
                </Link>
            )
            continue
        }

        const matchesPersonRegex = PERSON_REGEX.exec(part)
        if (matchesPersonRegex) {
            const personId = matchesPersonRegex[1]
            const personName = matchesPersonRegex[2]

            elements.push(
                <PersonDisplay key={part} person={{ id: personId }} displayName={personName} withIcon inline />
            )
            continue
        }

        const matchesActorRegex = ACTOR_REGEX.exec(part)
        if (matchesActorRegex) {
            const actorEmail = matchesActorRegex[1]

            elements.push(
                <ProfilePicture
                    key={part}
                    user={{
                        email: actorEmail,
                    }}
                    showName
                    size="sm"
                />
            )
            continue
        }

        elements.push(part)
    }

    return <>{elements}</>
}
