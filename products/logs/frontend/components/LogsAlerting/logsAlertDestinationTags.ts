import IconMicrosoftTeams from 'public/services/microsoft-teams.png'
import IconPagerDuty from 'public/services/pagerduty.png'
import IconSlack from 'public/services/slack.png'
import IconWebhook from 'public/services/webhook.svg'

import { LogsAlertDestinationTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

export const DESTINATION_TAGS = [
    { type: LogsAlertDestinationTypeEnumApi.Slack, label: 'Slack', icon: IconSlack },
    { type: LogsAlertDestinationTypeEnumApi.Webhook, label: 'Webhook', icon: IconWebhook },
    { type: LogsAlertDestinationTypeEnumApi.Teams, label: 'Teams', icon: IconMicrosoftTeams },
    { type: LogsAlertDestinationTypeEnumApi.Pagerduty, label: 'PagerDuty', icon: IconPagerDuty },
] as const
