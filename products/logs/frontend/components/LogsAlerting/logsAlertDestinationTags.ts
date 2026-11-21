import IconDiscord from 'public/services/discord.png'
import IconMicrosoftTeams from 'public/services/microsoft-teams.png'
import IconPagerDuty from 'public/services/pagerduty.png'
import IconSlack from 'public/services/slack.png'
import IconWebhook from 'public/services/webhook.svg'

import { AlertDestinationTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

export const DESTINATION_TAGS = [
    { type: AlertDestinationTypeEnumApi.Slack, label: 'Slack', icon: IconSlack },
    { type: AlertDestinationTypeEnumApi.Webhook, label: 'Webhook', icon: IconWebhook },
    { type: AlertDestinationTypeEnumApi.Teams, label: 'Teams', icon: IconMicrosoftTeams },
    { type: AlertDestinationTypeEnumApi.Discord, label: 'Discord', icon: IconDiscord },
    { type: AlertDestinationTypeEnumApi.Pagerduty, label: 'PagerDuty', icon: IconPagerDuty },
] as const
