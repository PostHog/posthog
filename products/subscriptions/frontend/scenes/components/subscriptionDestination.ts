import { parseCommaSeparatedSlackTargetDisplayLabels } from 'lib/utils/slackChannelValue'

import { TargetTypeEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

/** How a subscription's destinations read in the UI. */
export interface SubscriptionDestination {
    /**
     * One entry per destination. A webhook appears as its host, because anyone who has the full
     * URL can post to the channel.
     */
    parts: string[]
    /** Names one entry in a copy confirmation, or null where the entry is masked and copying it would mislead. */
    copyDescription: string | null
    /** Names the entries where a row shows a count instead of the list. */
    countNoun: string
}

function emailDestination(targetValue: string): SubscriptionDestination {
    return {
        parts: targetValue
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean),
        copyDescription: 'email recipient',
        countNoun: 'recipient',
    }
}

function slackDestination(targetValue: string): SubscriptionDestination {
    return {
        parts: parseCommaSeparatedSlackTargetDisplayLabels(targetValue),
        copyDescription: 'Slack destination',
        countNoun: 'channel',
    }
}

function webhookDestination(host: string): SubscriptionDestination {
    return { parts: [host], copyDescription: null, countNoun: 'destination' }
}

function webhookHost(url: string): string {
    try {
        // `hostname`, not `host`: an explicit `:443` would make this cell disagree with the
        // delivery history, where the backend records the bare host for the same destination.
        return new URL(url).hostname
    } catch {
        return 'Invalid URL'
    }
}

/** Reads `Subscription.target_value`, which holds the webhook URL itself. */
export function subscriptionDestination(targetType: string, targetValue: string): SubscriptionDestination {
    switch (targetType) {
        case TargetTypeEnumApi.Email:
            return emailDestination(targetValue)
        case TargetTypeEnumApi.Slack:
            return slackDestination(targetValue)
        case TargetTypeEnumApi.Teams:
        default:
            return webhookDestination(webhookHost(targetValue))
    }
}

/**
 * Reads `SubscriptionDelivery.target_value`, the send-time snapshot the API returns for delivery
 * history. For Teams the API already replaced the webhook URL with its host, or with the literal
 * "webhook" when the URL did not parse, so that value is shown as it arrives.
 */
export function deliveryDestination(targetType: string, targetValue: string): SubscriptionDestination {
    switch (targetType.toLowerCase()) {
        case TargetTypeEnumApi.Email:
            return emailDestination(targetValue)
        case TargetTypeEnumApi.Slack:
            return slackDestination(targetValue)
        case TargetTypeEnumApi.Teams:
            return webhookDestination(targetValue)
        default:
            return webhookDestination(webhookHost(targetValue))
    }
}
