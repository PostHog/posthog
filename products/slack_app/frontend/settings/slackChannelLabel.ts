import type { SlackChannelType } from '~/types'

export function slackChannelLabel(channel: SlackChannelType | undefined, slackChannelId: string): string {
    if (!channel?.name) {
        return slackChannelId
    }
    return `${channel.is_private ? '🔒' : '#'}${channel.name}`
}
