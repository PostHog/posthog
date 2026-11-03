import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { slackAppWorkspaceSetupLogic } from './slackAppWorkspaceSetupLogic'

export function SlackAppWorkspaceSetupDone(): JSX.Element {
    const { setup, skippedSteps } = useValues(slackAppWorkspaceSetupLogic)
    const { openSlackClicked } = useActions(slackAppWorkspaceSetupLogic)

    const workspaceName = setup?.slack_workspace_name || 'Your Slack workspace'

    return (
        <>
            <IconCheckCircle className="text-success text-4xl" />
            <div className="flex flex-col items-center gap-1 text-center">
                <h1 className="text-2xl font-bold m-0">{workspaceName} is set up. Now open Slack.</h1>
                <p className="text-secondary m-0">
                    Send PostHog a direct message, or mention @PostHog in any channel to ask a question.
                </p>
            </div>
            {skippedSteps.includes('ai_consent') ? (
                <LemonBanner type="warning" className="w-full">
                    PostHog can't answer in Slack until an organization admin allows AI data processing.
                </LemonBanner>
            ) : null}
            {setup?.open_slack_url ? (
                <LemonButton
                    type="primary"
                    to={setup.open_slack_url}
                    targetBlank
                    onClick={openSlackClicked}
                    data-attr="slack-app-workspace-setup-open-slack"
                >
                    Open PostHog in Slack
                </LemonButton>
            ) : null}
        </>
    )
}
