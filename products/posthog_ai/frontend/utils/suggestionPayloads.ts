import { Dayjs, dayjs } from 'lib/dayjs'
import { slackChannelId, slackChannelName } from 'lib/integrations/slackChannel'
import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import { PropertyFilterType, PropertyOperator } from '~/types'
import type { HogFunctionType } from '~/types'

import type { alertsCreate } from 'products/alerts/frontend/generated/api'
import type { AlertCreateDestinationApi } from 'products/alerts/frontend/generated/api.schemas'
import type { SignalScoutCreateApi } from 'products/signals/frontend/generated/api.schemas'
import {
    DEFAULT_SCOUT_DAILY_TIME,
    DEFAULT_SCOUT_WEEKLY_DAY,
    dayTimeToWeeklyCron,
    timeToDailyCron,
} from 'products/signals/frontend/inbox/utils/scoutRunsWindow'
import type { subscriptionsCreate } from 'products/subscriptions/frontend/generated/api'

import type {
    AlertSuggestionDirection,
    AlertTurnSuggestion,
    ErrorAlertTurnSuggestion,
    ScoutSuggestionCadence,
    ScoutTurnSuggestion,
    SubscriptionTurnSuggestion,
} from '../types/streamTypes'

/** The same default hour and weekday the scout settings form proposes. */
function cadenceToCron(cadence: ScoutSuggestionCadence): string {
    return cadence === 'daily'
        ? timeToDailyCron(DEFAULT_SCOUT_DAILY_TIME)
        : dayTimeToWeeklyCron(DEFAULT_SCOUT_WEEKLY_DAY, DEFAULT_SCOUT_DAILY_TIME)
}

export interface SlackDestinationInput {
    slackIntegrationId: number
    /** A `${channelId}|#${channelName}` picker value. */
    slackChannel: string
}

export interface ScoutCreateInput extends SlackDestinationInput {
    suggestion: ScoutTurnSuggestion
    cadence: ScoutSuggestionCadence
    /** The instructions the user reviewed on the card, which start as the drafted ones. */
    body: string
}

export function buildScoutCreatePayload({
    suggestion,
    cadence,
    body,
    slackIntegrationId,
    slackChannel,
}: ScoutCreateInput): SignalScoutCreateApi {
    return {
        display_name: suggestion.scout.displayName,
        description: suggestion.scout.description || suggestion.scout.displayName,
        body,
        config: {
            run_cron_schedule: cadenceToCron(cadence),
            output_destinations: {
                slack: { integration_id: slackIntegrationId, channel: slackChannel },
            },
            // A watch scout is valuable when it stays silent, which the inactivity sweep would read as dead.
            ...(suggestion.scout.mode === 'watch' ? { auto_pause_exempt: true } : {}),
        },
    }
}

export interface AlertCreateInput {
    suggestion: AlertTurnSuggestion
    direction: AlertSuggestionDirection
    changePercent: number
    insightId: number
    userId: number
}

export function buildAlertCreatePayload({
    suggestion,
    direction,
    changePercent,
    insightId,
    userId,
}: AlertCreateInput): Parameters<typeof alertsCreate>[1] {
    return {
        insight: insightId,
        subscribed_users: [userId],
        name: `${suggestion.alert.insightName}: ${changePercent}% ${direction}`,
        enabled: true,
        condition: { type: direction === 'decrease' ? 'relative_decrease' : 'relative_increase' },
        config: { type: 'TrendsAlertConfig', series_index: 0, check_ongoing_interval: false },
        // The alerts API reads a relative bound as a fraction of the previous period and fires above `upper`.
        threshold: { configuration: { type: 'percentage', bounds: { upper: changePercent / 100 } } },
        calculation_interval: 'daily',
    }
}

export function buildAlertDestinationPayload({
    slackIntegrationId,
    slackChannel,
}: SlackDestinationInput): AlertCreateDestinationApi {
    return {
        type: 'slack',
        slack_workspace_id: slackIntegrationId,
        slack_channel_id: slackChannelId(slackChannel),
        slack_channel_name: slackChannelName(slackChannel),
    }
}

const DELIVERY_HOUR = 9

/** The next 09:00 in the browser's clock, on a Monday for a weekly cadence. */
export function nextSubscriptionStart(cadence: ScoutSuggestionCadence, now: Dayjs = dayjs()): Dayjs {
    let start = now.hour(DELIVERY_HOUR).minute(0).second(0).millisecond(0)
    if (!start.isAfter(now)) {
        start = start.add(1, 'day')
    }
    while (cadence === 'weekly' && start.day() !== 1) {
        start = start.add(1, 'day')
    }
    return start
}

export interface SubscriptionCreateInput extends SlackDestinationInput {
    suggestion: SubscriptionTurnSuggestion
    cadence: ScoutSuggestionCadence
    insightId: number
    now?: Dayjs
}

export function buildSubscriptionCreatePayload({
    suggestion,
    cadence,
    insightId,
    slackIntegrationId,
    slackChannel,
    now,
}: SubscriptionCreateInput): Parameters<typeof subscriptionsCreate>[1] {
    const prefix = cadence === 'weekly' ? 'Weekly' : 'Daily'
    return {
        insight: insightId,
        title: `${prefix} report: ${suggestion.subscription.insightName}`.slice(0, 100),
        target_type: 'slack',
        integration_id: slackIntegrationId,
        target_value: slackChannel,
        frequency: cadence,
        interval: 1,
        byweekday: cadence === 'weekly' ? ['monday'] : undefined,
        start_date: nextSubscriptionStart(cadence, now).toISOString(),
        send_test_now: false,
    }
}

const ERROR_ALERT_SUB_TEMPLATE = 'error-tracking-issue-reopened'
const SLACK_TEMPLATE_ID = 'template-slack'

export interface ErrorAlertCreateInput extends SlackDestinationInput {
    suggestion: ErrorAlertTurnSuggestion
}

/**
 * The same destination the error tracking alert wizard writes for "post to Slack on issue reopened",
 * narrowed to one issue. A created-issue trigger would never fire for an issue that already exists.
 */
export function buildErrorAlertHogFunctionPayload({
    suggestion,
    slackIntegrationId,
    slackChannel,
}: ErrorAlertCreateInput): Partial<HogFunctionType> {
    const common = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[ERROR_ALERT_SUB_TEMPLATE]
    const slackTemplate = HOG_FUNCTION_SUB_TEMPLATES[ERROR_ALERT_SUB_TEMPLATE].find(
        (template) => template.template_id === SLACK_TEMPLATE_ID
    )
    const channelName = slackChannelName(slackChannel)
    return {
        type: common.type,
        template_id: SLACK_TEMPLATE_ID,
        name: `${slackTemplate?.name ?? 'Post to Slack on issue reopened'}${channelName ? `: #${channelName}` : ''}`,
        description: `Posts to Slack when "${suggestion.errorAlert.issueName}" reopens.`,
        enabled: true,
        masking: null,
        filters: {
            ...common.filters,
            properties: [
                {
                    key: '$exception_issue_id',
                    value: suggestion.errorAlert.issueId,
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
        },
        inputs: {
            ...slackTemplate?.inputs,
            slack_workspace: { value: slackIntegrationId },
            channel: { value: slackChannelId(slackChannel) },
        },
    }
}
