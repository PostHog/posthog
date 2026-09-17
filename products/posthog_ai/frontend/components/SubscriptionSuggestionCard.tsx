import { useActions, useValues } from 'kea'

import { LemonBanner, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { CADENCE_OPTIONS, cadenceLabel } from '../utils/turnSuggestions'
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
                Subscribed. {suggestion.subscription.insightName} goes to {slackChannelLabel} {cadenceLabel(cadence)} at
                9:00.
            </LemonBanner>
        )
    }

    return (
        <>
            <SuggestionDraftSummary name={suggestion.subscription.insightName}>
                <span className="text-xs text-secondary">
                    Posts the chart as it looks at 9:00, {cadence === 'weekly' ? 'on Mondays' : 'each day'}.
                </span>
            </SuggestionDraftSummary>

            <div className="flex flex-col gap-1">
                <LemonLabel>Sends</LemonLabel>
                <LemonSelect
                    size="small"
                    value={cadence}
                    options={CADENCE_OPTIONS}
                    onChange={(value) => value && setCadence(value)}
                />
            </div>

            <SlackDestinationSection {...props} connectHint="Connect Slack to get the chart posted to a channel." />

            <SuggestionActionRow
                {...props}
                label="Subscribe"
                dataAttr="posthog-ai-turn-suggestion-create-subscription"
                failedMessage="Couldn't create the subscription. Try again."
            />
        </>
    )
}
