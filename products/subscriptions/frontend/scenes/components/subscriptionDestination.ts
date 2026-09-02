import { parseCommaSeparatedSlackTargetDisplayLabels } from 'lib/utils/slackChannelValue'
import { pluralize } from 'lib/utils/strings'

import { SubscriptionTargetEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

export interface SubscriptionDestination {
    parts: string[]
    label: string
    title: string
    copyDescription: string | null
}

function destination(parts: string[], copyDescription: string | null, countNoun: string): SubscriptionDestination {
    return {
        parts,
        label: parts.length === 1 ? parts[0] : pluralize(parts.length, countNoun, undefined, true),
        title: parts.join(', '),
        copyDescription,
    }
}

function emailDestination(targetValue: string): SubscriptionDestination {
    return destination(
        targetValue
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean),
        'email recipient',
        'recipient'
    )
}

function slackDestination(targetValue: string): SubscriptionDestination {
    return destination(parseCommaSeparatedSlackTargetDisplayLabels(targetValue), 'Slack destination', 'channel')
}

function webhookDestination(host: string): SubscriptionDestination {
    return destination([host], null, 'destination')
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

export function subscriptionDestination(targetType: string, targetValue: string): SubscriptionDestination {
    switch (targetType) {
        case SubscriptionTargetEnumApi.Email:
            return emailDestination(targetValue)
        case SubscriptionTargetEnumApi.Slack:
            return slackDestination(targetValue)
        case SubscriptionTargetEnumApi.Teams:
            return webhookDestination(targetValue.includes('://') ? webhookHost(targetValue) : targetValue)
        default:
            return webhookDestination(webhookHost(targetValue))
    }
}

export function deliveryDestination(targetType: string, targetValue: string): SubscriptionDestination {
    switch (targetType.toLowerCase()) {
        case SubscriptionTargetEnumApi.Email:
            return emailDestination(targetValue)
        case SubscriptionTargetEnumApi.Slack:
            return slackDestination(targetValue)
        case SubscriptionTargetEnumApi.Teams:
            return webhookDestination(targetValue)
        default:
            return webhookDestination(webhookHost(targetValue))
    }
}
