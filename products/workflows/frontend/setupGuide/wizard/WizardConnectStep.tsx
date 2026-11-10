import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { IconSlack } from 'lib/lemon-ui/icons'

import { onboardingWizardUrl } from './onboardingWizardSteps'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

export function WizardConnectStep(): JSX.Element {
    const { connectionsNeeded, missingConnections, selectedTemplateId } = useValues(workflowsOnboardingWizardLogic)

    if (connectionsNeeded.length === 0) {
        return (
            <div className="flex items-center gap-2">
                <IconCheckCircle className="size-5 text-success" />
                <span>This template needs no other tools. Continue to review it.</span>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {connectionsNeeded.map((connection) => {
                const isConnected = !missingConnections.includes(connection)
                return (
                    <div
                        key={connection}
                        className="flex flex-wrap items-center justify-between gap-2 p-3 border rounded"
                    >
                        <div className="flex items-center gap-2">
                            <IconSlack className="size-5" />
                            <span className="font-semibold">Slack</span>
                            <span className="text-secondary">Posts messages to a channel in your workspace.</span>
                        </div>
                        {isConnected ? (
                            <span className="flex items-center gap-1 text-success">
                                <IconCheckCircle className="size-5" />
                                <span>Connected</span>
                            </span>
                        ) : (
                            <LemonButton
                                type="primary"
                                size="small"
                                disableClientSideRouting
                                to={api.integrations.authorizeUrl({
                                    kind: connection,
                                    next: onboardingWizardUrl('automation', {
                                        step: 'connect',
                                        template: selectedTemplateId ?? undefined,
                                    }),
                                })}
                                data-attr="workflows-onboarding-wizard-connect-slack"
                            >
                                Connect Slack
                            </LemonButton>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
