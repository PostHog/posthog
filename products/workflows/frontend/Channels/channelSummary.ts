import type { IntegrationType } from '~/types'

import type { ChannelType } from './MessageChannels'

// pinned: integration kinds, also sent as the `kind` property of the channel setup event - renaming breaks dashboards
export const CATALOG_CHANNELS: ChannelType[] = ['email', 'slack', 'twilio', 'firebase', 'apns']
export const PUSH_CHANNELS: ChannelType[] = ['firebase', 'apns']

// pinned: analytics property values of the channel setup event - renaming breaks dashboards
export type ChannelStatus = 'not-set-up' | 'active' | 'needs-verification' | 'needs-attention'

export interface ChannelSummary {
    kind: ChannelType
    status: ChannelStatus
    count: number
}

export const CHANNEL_COPY: Record<ChannelType, { name: string; description: string }> = {
    email: { name: 'Email', description: 'Send email from your own domain.' },
    slack: { name: 'Slack', description: "Post messages to your team's Slack channels." },
    twilio: { name: 'Twilio', description: 'Send SMS messages to your users.' },
    firebase: { name: 'Firebase Cloud Messaging', description: 'Send push notifications to Android apps.' },
    apns: { name: 'Apple Push Notifications', description: 'Send push notifications to iOS apps.' },
}

/**
 * An email channel sends only after its domain is verified, so a connected but unverified address is not active.
 * Any connection with an error marks the whole channel, because a step that uses it can fail.
 */
export function summarizeChannel(
    kind: ChannelType,
    integrations: Pick<IntegrationType, 'kind' | 'config' | 'errors'>[]
): ChannelSummary {
    const connected = integrations.filter((integration) => integration.kind === kind)
    const count = connected.length
    if (count === 0) {
        return { kind, status: 'not-set-up', count }
    }
    if (connected.some((integration) => !!integration.errors)) {
        return { kind, status: 'needs-attention', count }
    }
    if (kind === 'email' && !connected.some((integration) => integration.config?.verified === true)) {
        return { kind, status: 'needs-verification', count }
    }
    return { kind, status: 'active', count }
}
