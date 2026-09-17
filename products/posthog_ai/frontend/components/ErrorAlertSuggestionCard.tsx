import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { slackChannelDisplayName } from 'lib/integrations/slackChannel'

import { errorAlertSuggestionLogic } from '../logics/errorAlertSuggestionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { SlackDestinationSection } from './SlackDestinationSection'

export function ErrorAlertSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = errorAlertSuggestionLogic(props)
    const { suggestion, slackChannel, createdAlert, createdAlertLoading, createDisabledReason, createError, alertUrl } =
        useValues(logic)
    const { createAlert } = useActions(logic)

    if (!suggestion) {
        return null
    }
    if (createdAlert) {
        return (
            <LemonBanner type="success" action={alertUrl ? { to: alertUrl, children: 'View alert' } : undefined}>
                Alert created. {slackChannel ? slackChannelDisplayName(slackChannel) : 'Slack'} gets a message when this
                issue reopens.
            </LemonBanner>
        )
    }

    return (
        <>
            <div className="flex flex-col gap-0.5 rounded bg-surface-secondary px-2 py-1.5">
                <span className="text-sm font-medium">{suggestion.errorAlert.issueName}</span>
                <span className="text-xs text-secondary">
                    Posts to Slack when this issue reopens after being resolved.
                </span>
            </div>

            <SlackDestinationSection {...props} connectHint="Connect Slack to get the alert posted to a channel." />

            {createError && <LemonBanner type="error">Couldn't create the alert. Try again.</LemonBanner>}

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={createAlert}
                    loading={createdAlertLoading}
                    disabledReason={createDisabledReason ?? undefined}
                    data-attr="posthog-ai-turn-suggestion-create-error-alert"
                >
                    Create alert
                </LemonButton>
            </div>
        </>
    )
}
