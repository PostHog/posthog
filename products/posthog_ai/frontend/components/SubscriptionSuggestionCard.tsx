import { useActions, useValues } from 'kea'

import { LemonBanner, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { CADENCE_OPTIONS } from '../utils/turnSuggestions'
import { SlackDestinationSection } from './SlackDestinationSection'
import { SuggestionActionRow } from './SuggestionActionRow'
import { SuggestionDraftSummary } from './SuggestionDraftSummary'

export function SubscriptionSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = suggestionActionLogic(props)
    const { suggestion, cadence, accepted, slackChannelLabel } = useValues(logic)
    const { setCadence } = useActions(logic)

    if (suggestion?.kind !== 'subscription') {
        return null
    }
    if (accepted) {
        return (
            <LemonBanner
                type="success"
                action={accepted.url ? { to: accepted.url, children: 'View subscription' } : undefined}
            >
                Subscribed. {slackChannelLabel} gets {suggestion.subscription.insightName}{' '}
                {cadence === 'weekly' ? 'every Monday' : 'every day'} at 9:00.
            </LemonBanner>
        )
    }

    return (
        <>
            <SuggestionDraftSummary name={suggestion.subscription.insightName} />

            <div className="flex flex-col gap-1">
                <LemonLabel>Sends</LemonLabel>
                <LemonSelect
                    size="small"
                    value={cadence}
                    options={CADENCE_OPTIONS}
                    onChange={(value) => value && setCadence(value)}
                />
            </div>

            <SlackDestinationSection {...props} connectHint="Connect Slack to post the chart to a channel." />

            <SuggestionActionRow
                {...props}
                label="Subscribe"
                dataAttr="posthog-ai-turn-suggestion-create-subscription"
                failedMessage="Couldn't create the subscription. Try again."
            />
        </>
    )
}
