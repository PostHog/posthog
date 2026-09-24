import {
    ALERT_DIRECTIONS,
    type AlertSuggestionDirection,
    type AlertSuggestionDraft,
    type ErrorAlertSuggestionDraft,
    type IncidentOutline,
    type NotebookSuggestionDraft,
    SCOUT_CADENCES,
    SCOUT_MODES,
    type ScoutSuggestionCadence,
    type ScoutSuggestionDraft,
    type ScoutSuggestionMode,
    type SubscriptionSuggestionDraft,
    type SuggestedInsightRef,
    type TurnSuggestion,
} from '../types/streamTypes'
import type { PosthogTurnSuggestionParams, SuggestedInsightRefParams } from '../types/wireTypes'

export const CADENCE_OPTIONS: { value: ScoutSuggestionCadence; label: string }[] = [
    { value: 'daily', label: 'Every day' },
    { value: 'weekly', label: 'Every week' },
]

export const ALERT_DIRECTION_OPTIONS: { value: AlertSuggestionDirection; label: string }[] = [
    { value: 'decrease', label: 'Drops' },
    { value: 'increase', label: 'Rises' },
]

export const SCOUT_MODE_HINTS: Record<ScoutSuggestionMode, string | null> = {
    report: null,
    watch: 'Posts only when the number crosses a threshold.',
    investigate: 'When the metric drops, runs this investigation again and posts what it finds.',
    digest: 'Posts every metric from this conversation together.',
}

function isOneOf<T extends string>(table: readonly T[], value: unknown): value is T {
    return typeof value === 'string' && (table as readonly string[]).includes(value)
}

function nonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value.trim().length > 0
}

const TURN_SUGGESTION_KINDS: readonly TurnSuggestion['kind'][] = [
    'scout',
    'notebook',
    'alert',
    'subscription',
    'error_alert',
]

function parseScoutDraft(scout: PosthogTurnSuggestionParams['scout']): ScoutSuggestionDraft | null {
    if (
        !scout ||
        !nonEmptyString(scout.displayName) ||
        !nonEmptyString(scout.body) ||
        !isOneOf(SCOUT_CADENCES, scout.cadence)
    ) {
        return null
    }
    return {
        // Frames persisted before scouts had modes carry none; those were all plain reports.
        mode: isOneOf(SCOUT_MODES, scout.mode) ? scout.mode : 'report',
        displayName: scout.displayName,
        description: nonEmptyString(scout.description) ? scout.description : '',
        body: scout.body,
        cadence: scout.cadence,
    }
}

function parseIncident(
    incident: NonNullable<PosthogTurnSuggestionParams['notebook']>['incident']
): IncidentOutline | null {
    if (!incident || !nonEmptyString(incident.cause)) {
        return null
    }
    return {
        timeline: nonEmptyString(incident.timeline) ? incident.timeline : '',
        cause: incident.cause,
        fix: nonEmptyString(incident.fix) ? incident.fix : '',
    }
}

function parseNotebookDraft(notebook: PosthogTurnSuggestionParams['notebook']): NotebookSuggestionDraft | null {
    if (!notebook || !nonEmptyString(notebook.title)) {
        return null
    }
    return {
        title: notebook.title,
        summary: nonEmptyString(notebook.summary) ? notebook.summary : '',
        incident: parseIncident(notebook.incident),
    }
}

function parseInsightRef(insight: SuggestedInsightRefParams | undefined): SuggestedInsightRef | null {
    if (!insight || !nonEmptyString(insight.insightShortId)) {
        return null
    }
    return {
        insightShortId: insight.insightShortId,
        insightId: typeof insight.insightId === 'number' ? insight.insightId : null,
        insightName: nonEmptyString(insight.insightName) ? insight.insightName : 'this insight',
    }
}

function parseAlertDraft(alert: PosthogTurnSuggestionParams['alert']): AlertSuggestionDraft | null {
    const insight = parseInsightRef(alert)
    if (!insight || !alert || !isOneOf(ALERT_DIRECTIONS, alert.direction)) {
        return null
    }
    if (typeof alert.changePercent !== 'number' || !(alert.changePercent > 0)) {
        return null
    }
    return { ...insight, direction: alert.direction, changePercent: Math.round(alert.changePercent) }
}

function parseSubscriptionDraft(
    subscription: PosthogTurnSuggestionParams['subscription']
): SubscriptionSuggestionDraft | null {
    const insight = parseInsightRef(subscription)
    if (!insight || !subscription || !isOneOf(SCOUT_CADENCES, subscription.cadence)) {
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

export function parseTurnSuggestionParams(params: unknown): TurnSuggestion | null {
    if (!params || typeof params !== 'object') {
        return null
    }
    const { turnIndex, kind, intent, confidence, title, description, ...drafts } = params as PosthogTurnSuggestionParams
    if (
        typeof turnIndex !== 'number' ||
        !Number.isInteger(turnIndex) ||
        turnIndex < 0 ||
        !isOneOf(TURN_SUGGESTION_KINDS, kind) ||
        !nonEmptyString(title) ||
        !nonEmptyString(description)
    ) {
        return null
    }
    const base = {
        turnIndex,
        intent: typeof intent === 'string' ? intent : 'unknown',
        confidence: typeof confidence === 'number' ? confidence : 0,
        title,
        description,
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

export function cadenceLabel(cadence: ScoutSuggestionCadence): string {
    return cadence === 'daily' ? 'every day' : 'every week'
}
