import { CyclotronJobFiltersType, HogFunctionType, PropertyFilterType, PropertyOperator } from '~/types'

import type { VisionAlertConfigurationApi } from '../generated/api.schemas'

// pinned: internal event ids — HogFunction destination filters match on them
export const VISION_ALERT_FIRING_EVENT_ID = '$replay_vision_alert_firing'
export const VISION_ALERT_RESOLVED_EVENT_ID = '$replay_vision_alert_resolved'
export const VISION_ALERT_AUTO_DISABLED_EVENT_ID = '$replay_vision_alert_auto_disabled'
export const VISION_ALERT_ERRORED_EVENT_ID = '$replay_vision_alert_errored'
export const VISION_ALERT_MATCH_EVENT_ID = '$replay_vision_alert_match'

export const VISION_ALERT_NOTIFICATION_TYPE_SLACK = 'slack' as const
export const VISION_ALERT_NOTIFICATION_TYPE_WEBHOOK = 'webhook' as const

export type VisionAlertNotificationType =
    | typeof VISION_ALERT_NOTIFICATION_TYPE_SLACK
    | typeof VISION_ALERT_NOTIFICATION_TYPE_WEBHOOK

export type PendingVisionAlertNotification =
    | {
          type: typeof VISION_ALERT_NOTIFICATION_TYPE_SLACK
          slackWorkspaceId: number
          slackChannelId: string
          slackChannelName?: string
      }
    | {
          type: typeof VISION_ALERT_NOTIFICATION_TYPE_WEBHOOK
          webhookUrl: string
      }

export type VisionAlertDestinationGroup = {
    key: string
    type: VisionAlertNotificationType
    label: string
    hogFunctions: HogFunctionType[]
    enabled: boolean
}

// Matches every HogFunction belonging to this alert regardless of event kind: the create
// endpoint fans out into one HogFunction per event kind, and the alert_id property alone
// identifies the whole group.
export function buildVisionAlertFilterConfig(alertId: string): CyclotronJobFiltersType {
    return {
        properties: [
            {
                key: 'alert_id',
                value: alertId,
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ],
    }
}

export function groupVisionAlertDestinations(hogFunctions: HogFunctionType[]): VisionAlertDestinationGroup[] {
    const groups = new Map<string, VisionAlertDestinationGroup>()
    for (const hf of hogFunctions) {
        const templateId = hf.template_id ?? hf.template?.id
        const slackChannelValue = hf.inputs?.channel?.value as string | undefined
        const webhookUrl = hf.inputs?.url?.value as string | undefined

        let key: string
        let type: VisionAlertNotificationType
        let label: string
        if (templateId === 'template-slack') {
            type = VISION_ALERT_NOTIFICATION_TYPE_SLACK
            key = `slack:${slackChannelValue ?? hf.id}`
            label = 'Slack'
        } else {
            type = VISION_ALERT_NOTIFICATION_TYPE_WEBHOOK
            key = `webhook:${webhookUrl ?? hf.id}`
            label = webhookUrl ?? hf.name
        }

        const existing = groups.get(key)
        if (existing) {
            existing.hogFunctions.push(hf)
            existing.enabled = existing.enabled || !!hf.enabled
        } else {
            groups.set(key, { key, type, label, hogFunctions: [hf], enabled: !!hf.enabled })
        }
    }
    return Array.from(groups.values())
}

export function conditionSummary(alert: VisionAlertConfigurationApi): string {
    if (alert.kind === 'match') {
        return 'every matching observation'
    }
    const metricLabel = alert.metric === 'avg_score' ? 'average score' : 'matching observations'
    const directionLabel = alert.direction === 'below' ? 'at or below' : 'at or above'
    const windowLabel = alert.window_days === 1 ? '24 hours' : `${alert.window_days} days`
    return `${metricLabel} ${directionLabel} ${alert.threshold} in the last ${windowLabel}`
}

export function selectionSummary(alert: VisionAlertConfigurationApi): string {
    const selection = (alert.selection ?? {}) as Record<string, unknown>
    const parts: string[] = []
    const verdict = selection.verdict as string[] | undefined
    const tags = selection.tags as string[] | undefined
    if (verdict?.length) {
        parts.push(`verdict ${verdict.join(', ')}`)
    }
    if (tags?.length) {
        parts.push(`tags ${tags.join(', ')}`)
    }
    if (selection.min_score !== undefined && selection.min_score !== null) {
        parts.push(`score ≥ ${selection.min_score}`)
    }
    if (selection.max_score !== undefined && selection.max_score !== null) {
        parts.push(`score ≤ ${selection.max_score}`)
    }
    return parts.length ? parts.join(', ') : 'all observations'
}
