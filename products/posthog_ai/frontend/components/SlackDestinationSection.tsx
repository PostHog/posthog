import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SlackDestinationPicker } from 'lib/components/Comments/SlackDestinationPicker'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { slackDestinationLogic } from '../logics/slackDestinationLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'

export interface SlackDestinationSectionProps extends TurnSuggestionLogicProps {
    /** What connecting Slack buys the user on this card, shown when the project has no workspace yet. */
    connectHint: string
}

export function SlackDestinationSection({ connectHint, ...logicProps }: SlackDestinationSectionProps): JSX.Element {
    const logic = slackDestinationLogic(logicProps)
    const { slackIntegrationId, slackChannel, hasSlackWorkspace, slackWorkspacesLoading, waitingForSlack } =
        useValues(logic)
    const { setSlackIntegrationId, setSlackChannel, connectSlackClicked } = useActions(logic)

    if (slackWorkspacesLoading) {
        return (
            <div className="flex justify-center p-2">
                <Spinner />
            </div>
        )
    }
    if (hasSlackWorkspace) {
        return (
            <SlackDestinationPicker
                integrationId={slackIntegrationId}
                channel={slackChannel}
                onIntegrationChange={setSlackIntegrationId}
                onChannelChange={setSlackChannel}
            />
        )
    }
    return (
        <div className="flex flex-col gap-2">
            <span className="text-sm text-secondary">
                {connectHint} It opens in a new tab, and this card updates when you come back.
            </span>
            <div className="flex items-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    to={api.integrations.authorizeUrl({ kind: 'slack', next: urls.settings('project-integrations') })}
                    targetBlank
                    disableClientSideRouting
                    onClick={connectSlackClicked}
                    data-attr="posthog-ai-turn-suggestion-connect-slack"
                >
                    Connect Slack
                </LemonButton>
                {waitingForSlack && (
                    <span className="flex items-center gap-1 text-xs text-secondary">
                        <Spinner className="text-sm" />
                        Waiting for Slack
                    </span>
                )}
            </div>
        </div>
    )
}
