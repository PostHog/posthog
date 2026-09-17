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

/** One line under the drafted scout that says how this mode behaves differently from a plain report. */
export const SCOUT_MODE_HINTS: Record<ScoutSuggestionMode, string | null> = {
    report: null,
    watch: 'Posts only when the number moves past the bound in the prompt, and stays silent otherwise.',
    investigate: 'Reruns this investigation when the metric dips again and posts what it finds.',
    check_back: 'Checks whether the metric recovered and posts when it has. Pause the scout once it did.',
    digest: 'Covers every metric from this conversation in one post.',
}

function isOneOf<T extends string>(table: readonly T[], value: unknown): value is T {
    return typeof value === 'string' && (table as readonly string[]).includes(value)
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

export function cadenceLabel(cadence: ScoutSuggestionCadence): string {
    return cadence === 'daily' ? 'every day' : 'every week'
}
