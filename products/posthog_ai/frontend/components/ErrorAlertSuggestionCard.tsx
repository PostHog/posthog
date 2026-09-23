import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { SlackDestinationSection } from './SlackDestinationSection'
import { SuggestionActionRow } from './SuggestionActionRow'
import { SuggestionDraftSummary } from './SuggestionDraftSummary'

export function ErrorAlertSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const { suggestion, accepted, slackChannelLabel } = useValues(suggestionActionLogic(props))

    if (suggestion?.kind !== 'error_alert') {
        return null
    }
    if (accepted) {
        return (
            <LemonBanner
                type="success"
                action={accepted.url ? { to: accepted.url, children: 'View alert' } : undefined}
            >
                Alert created. {slackChannelLabel} gets a message if this issue reopens.
            </LemonBanner>
        )
    }

    return (
        <>
            <SuggestionDraftSummary name={suggestion.errorAlert.issueName} />

            <SlackDestinationSection {...props} connectHint="Connect Slack to post the alert to a channel." />

            <SuggestionActionRow
                {...props}
                label="Create alert"
                dataAttr="posthog-ai-turn-suggestion-create-error-alert"
                failedMessage="Couldn't create the alert. Try again."
            />
        </>
    )
}
