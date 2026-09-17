import { Dayjs, dayjs } from 'lib/dayjs'
import { slackChannelDisplayName, slackChannelId } from 'lib/integrations/slackChannel'
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
    AlertSuggestionDraft,
    AlertTurnSuggestion,
    ErrorAlertSuggestionDraft,
    ErrorAlertTurnSuggestion,
    IncidentOutline,
    NotebookSuggestionDraft,
    ScoutSuggestionCadence,
    ScoutSuggestionDraft,
    ScoutSuggestionMode,
    ScoutTurnSuggestion,
    SubscriptionSuggestionDraft,
    SubscriptionTurnSuggestion,
    SuggestedInsightRef,
    TurnSuggestion,
} from '../types/streamTypes'
import type { PosthogTurnSuggestionParams } from '../types/wireTypes'

export const CADENCE_OPTIONS: { value: ScoutSuggestionCadence; label: string }[] = [
    { value: 'daily', label: 'Every day' },
    { value: 'weekly', label: 'Every week' },
]

export const ALERT_DIRECTION_OPTIONS: { value: AlertSuggestionDirection; label: string }[] = [
    { value: 'decrease', label: 'Drops' },
    { value: 'increase', label: 'Rises' },
]

const SCOUT_MODES: ScoutSuggestionMode[] = ['report', 'watch', 'investigate', 'check_back', 'digest']

/** One line under the drafted scout that says how this mode behaves differently from a plain report. */
export const SCOUT_MODE_HINTS: Record<ScoutSuggestionMode, string | null> = {
    report: null,
    watch: 'Posts only when the number moves past the bound in the prompt. Quiet runs stay quiet.',
    investigate: 'Reruns this investigation when the metric dips again and posts what it finds.',
    check_back: 'Checks whether the metric recovered and posts when it has. Pause the scout once it did.',
    digest: 'Covers every metric from this conversation in one post.',
}

function isCadence(value: unknown): value is ScoutSuggestionCadence {
    return value === 'daily' || value === 'weekly'
}

function isScoutMode(value: unknown): value is ScoutSuggestionMode {
    return SCOUT_MODES.includes(value as ScoutSuggestionMode)
}

function isAlertDirection(value: unknown): value is AlertSuggestionDirection {
    return value === 'decrease' || value === 'increase'
}

function nonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value.trim().length > 0
}

const FALLBACK_COPY: Record<TurnSuggestion['kind'], { title: string; description: string }> = {
    scout: {
        title: 'Turn this into a scout',
        description: 'Run this analysis on a schedule and post the results to Slack.',
    },
    notebook: {
        title: 'Save this investigation to a notebook',
        description: 'Keep the question, the queries and the findings together to share and revisit.',
    },
    alert: {
        title: 'Get a Slack message when this moves',
        description: 'An alert on the saved insight posts to a channel when the number changes more than expected.',
    },
    subscription: {
        title: 'Get this chart in Slack on a schedule',
        description: 'A subscription posts the saved insight to a channel every day or every week.',
    },
    error_alert: {
        title: 'Get told when this error comes back',
        description: 'An alert on the issue posts to Slack when it reopens.',
    },
}

function parseScoutDraft(scout: PosthogTurnSuggestionParams['scout']): ScoutSuggestionDraft | null {
    if (!scout || !nonEmptyString(scout.displayName) || !nonEmptyString(scout.body) || !isCadence(scout.cadence)) {
        return null
    }
    return {
        mode: isScoutMode(scout.mode) ? scout.mode : 'report',
        displayName: scout.displayName,
        description: nonEmptyString(scout.description) ? scout.description : '',
        body: scout.body,
        cadence: scout.cadence,
    }
}

function parseIncident(
    incident: NonNullable<PosthogTurnSuggestionParams['notebook']>['incident']
): IncidentOutline | null {
    if (!incident) {
        return null
    }
    const outline = {
        timeline: nonEmptyString(incident.timeline) ? incident.timeline : '',
        cause: nonEmptyString(incident.cause) ? incident.cause : '',
        fix: nonEmptyString(incident.fix) ? incident.fix : '',
    }
    return outline.timeline || outline.cause || outline.fix ? outline : null
}

function parseNotebookDraft(notebook: PosthogTurnSuggestionParams['notebook']): NotebookSuggestionDraft | null {
    if (!notebook || !nonEmptyString(notebook.title)) {
        return null
    }
    const incident = notebook.template === 'incident' ? parseIncident(notebook.incident) : null
    return {
        template: incident ? 'incident' : 'conversation',
        title: notebook.title,
        summary: nonEmptyString(notebook.summary) ? notebook.summary : '',
        incident,
    }
}

function parseInsightRef(
    insight: PosthogTurnSuggestionParams['alert'] | PosthogTurnSuggestionParams['subscription']
): SuggestedInsightRef | null {
    if (!insight || !nonEmptyString(insight.insightShortId)) {
        return null
    }
    return {
        insightShortId: insight.insightShortId,
        insightId: typeof insight.insightId === 'number' ? insight.insightId : null,
        insightName: nonEmptyString(insight.insightName) ? insight.insightName : 'this insight',
        queryKind: nonEmptyString(insight.queryKind) ? insight.queryKind : '',
    }
}

function parseAlertDraft(alert: PosthogTurnSuggestionParams['alert']): AlertSuggestionDraft | null {
    const insight = parseInsightRef(alert)
    if (!insight || !alert || !isAlertDirection(alert.direction)) {
        return null
    }
    const changePercent =
        typeof alert.changePercent === 'number' && alert.changePercent > 0 ? Math.round(alert.changePercent) : 20
    return { ...insight, direction: alert.direction, changePercent }
}

function parseSubscriptionDraft(
    subscription: PosthogTurnSuggestionParams['subscription']
): SubscriptionSuggestionDraft | null {
    const insight = parseInsightRef(subscription)
    if (!insight || !subscription || !isCadence(subscription.cadence)) {
        return null
    }
    return { ...insight, cadence: subscription.cadence }
}

function parseErrorAlertDraft(errorAlert: PosthogTurnSuggestionParams['errorAlert']): ErrorAlertSuggestionDraft | null {
    if (!errorAlert || !nonEmptyString(errorAlert.issueId)) {
        return null
    }
    return {
        issueId: errorAlert.issueId,
        issueName: nonEmptyString(errorAlert.issueName) ? errorAlert.issueName : 'this issue',
    }
}

function isSuggestionKind(kind: unknown): kind is TurnSuggestion['kind'] {
    return typeof kind === 'string' && kind in FALLBACK_COPY
}

/** Narrows a `_posthog/turn_suggestion` frame; anything the card cannot act on is dropped. */
export function parseTurnSuggestionParams(params: unknown): TurnSuggestion | null {
    if (!params || typeof params !== 'object') {
        return null
    }
    const { turnIndex, kind, intent, confidence, title, description, ...drafts } = params as PosthogTurnSuggestionParams
    if (typeof turnIndex !== 'number' || !Number.isInteger(turnIndex) || turnIndex < 0 || !isSuggestionKind(kind)) {
        return null
    }
    const base = {
        turnIndex,
        intent: typeof intent === 'string' ? intent : 'unknown',
        confidence: typeof confidence === 'number' ? confidence : 0,
        title: nonEmptyString(title) ? title : FALLBACK_COPY[kind].title,
        description: nonEmptyString(description) ? description : FALLBACK_COPY[kind].description,
    }
    switch (kind) {
        case 'scout': {
            const scout = parseScoutDraft(drafts.scout)
            return scout ? { ...base, kind, scout } : null
        }
        case 'notebook': {
            const notebook = parseNotebookDraft(drafts.notebook)
            return notebook ? { ...base, kind, notebook } : null
        }
        case 'alert': {
            const alert = parseAlertDraft(drafts.alert)
            return alert ? { ...base, kind, alert } : null
        }
        case 'subscription': {
            const subscription = parseSubscriptionDraft(drafts.subscription)
            return subscription ? { ...base, kind, subscription } : null
        }
        case 'error_alert': {
            const errorAlert = parseErrorAlertDraft(drafts.errorAlert)
            return errorAlert ? { ...base, kind, errorAlert } : null
        }
    }
}

/** The same default hour and weekday the scout settings form proposes. */
function cadenceToCron(cadence: ScoutSuggestionCadence): string {
    return cadence === 'daily'
        ? timeToDailyCron(DEFAULT_SCOUT_DAILY_TIME)
        : dayTimeToWeeklyCron(DEFAULT_SCOUT_WEEKLY_DAY, DEFAULT_SCOUT_DAILY_TIME)
}

export function cadenceLabel(cadence: ScoutSuggestionCadence): string {
    return cadence === 'daily' ? 'every day' : 'every week'
}

/** The `#name` half of a picker value without the hash, or nothing for a bare channel id. */
function slackChannelName(channelValue: string): string | undefined {
    return channelValue.includes('|') ? slackChannelDisplayName(channelValue).replace(/^#/, '') : undefined
}

export interface SlackDestinationInput {
    slackIntegrationId: number
    /** A `${channelId}|#${channelName}` picker value. */
    slackChannel: string
}

export interface ScoutCreateInput extends SlackDestinationInput {
    suggestion: ScoutTurnSuggestion
    cadence: ScoutSuggestionCadence
}

export function buildScoutCreatePayload({
    suggestion,
    cadence,
    slackIntegrationId,
    slackChannel,
}: ScoutCreateInput): SignalScoutCreateApi {
    return {
        display_name: suggestion.scout.displayName,
        description: suggestion.scout.description || suggestion.scout.displayName,
        body: suggestion.scout.body,
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
        config: { type: 'TrendsAlertConfig', series_index: 0 },
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

/** The next 09:00 in the browser's clock, on a Monday for a weekly cadence, the way the subscription wizard does. */
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
