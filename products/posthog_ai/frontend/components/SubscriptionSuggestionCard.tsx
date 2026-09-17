import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { slackChannelDisplayName } from 'lib/integrations/slackChannel'

import { subscriptionSuggestionLogic } from '../logics/subscriptionSuggestionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { CADENCE_OPTIONS, cadenceLabel } from '../utils/turnSuggestions'
import { SlackDestinationSection } from './SlackDestinationSection'

export function SubscriptionSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = subscriptionSuggestionLogic(props)
    const {
        suggestion,
        cadence,
        slackChannel,
        createdSubscription,
        createdSubscriptionLoading,
        createDisabledReason,
        createError,
        subscriptionUrl,
    } = useValues(logic)
    const { setCadence, createSubscription } = useActions(logic)

    if (!suggestion) {
        return null
    }
    if (createdSubscription) {
        return (
            <LemonBanner
                type="success"
                action={subscriptionUrl ? { to: subscriptionUrl, children: 'View subscription' } : undefined}
            >
                Subscribed. {suggestion.subscription.insightName} goes to{' '}
                {slackChannel ? slackChannelDisplayName(slackChannel) : 'Slack'} {cadenceLabel(cadence)} at 9:00.
            </LemonBanner>
        )
    }

    return (
        <>
            <div className="flex flex-col gap-0.5 rounded bg-surface-secondary px-2 py-1.5">
                <span className="text-sm font-medium">{suggestion.subscription.insightName}</span>
                <span className="text-xs text-secondary">
                    Posts the chart as it looks at 9:00, {cadence === 'weekly' ? 'on Mondays' : 'each day'}.
                </span>
            </div>

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

            {createError && <LemonBanner type="error">Couldn't create the subscription. Try again.</LemonBanner>}

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={createSubscription}
                    loading={createdSubscriptionLoading}
                    disabledReason={createDisabledReason ?? undefined}
                    data-attr="posthog-ai-turn-suggestion-create-subscription"
                >
                    Subscribe
                </LemonButton>
            </div>
        </>
    )
}
