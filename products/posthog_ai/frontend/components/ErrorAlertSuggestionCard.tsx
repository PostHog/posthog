import { useValues } from 'kea'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { SlackDestinationSection } from './SlackDestinationSection'
import { SuggestionAcceptedBanner } from './SuggestionAcceptedBanner'
import { SuggestionActionRow } from './SuggestionActionRow'
import { SuggestionDraftSummary } from './SuggestionDraftSummary'

export function ErrorAlertSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const { suggestion, accepted, slackChannelLabel } = useValues(suggestionActionLogic(props))

    if (suggestion?.kind !== 'error_alert') {
        return null
    }
    if (accepted) {
        return (
            <SuggestionAcceptedBanner accepted={accepted} linkLabel="View alert">
                Alert created. {slackChannelLabel} gets a message if this issue reopens.
            </SuggestionAcceptedBanner>
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
