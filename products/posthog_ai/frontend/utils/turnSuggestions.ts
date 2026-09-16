import type { SignalScoutCreateApi } from 'products/signals/frontend/generated/api.schemas'
import {
    DEFAULT_SCOUT_DAILY_TIME,
    DEFAULT_SCOUT_WEEKLY_DAY,
    dayTimeToWeeklyCron,
    timeToDailyCron,
} from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import type {
    NotebookSuggestionDraft,
    ScoutSuggestionCadence,
    ScoutSuggestionDraft,
    ScoutTurnSuggestion,
    TurnSuggestion,
} from '../types/streamTypes'
import type { PosthogTurnSuggestionParams } from '../types/wireTypes'

export const CADENCE_OPTIONS: { value: ScoutSuggestionCadence; label: string }[] = [
    { value: 'daily', label: 'Every day' },
    { value: 'weekly', label: 'Every week' },
]

function isCadence(value: unknown): value is ScoutSuggestionCadence {
    return value === 'daily' || value === 'weekly'
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
}

function parseScoutDraft(scout: PosthogTurnSuggestionParams['scout']): ScoutSuggestionDraft | null {
    if (!scout || !nonEmptyString(scout.displayName) || !nonEmptyString(scout.body) || !isCadence(scout.cadence)) {
        return null
    }
    return {
        displayName: scout.displayName,
        description: nonEmptyString(scout.description) ? scout.description : '',
        body: scout.body,
        cadence: scout.cadence,
    }
}

function parseNotebookDraft(notebook: PosthogTurnSuggestionParams['notebook']): NotebookSuggestionDraft | null {
    if (!notebook || !nonEmptyString(notebook.title)) {
        return null
    }
    return { title: notebook.title, summary: nonEmptyString(notebook.summary) ? notebook.summary : '' }
}

/** Narrows a `_posthog/turn_suggestion` frame; anything the card cannot act on is dropped. */
export function parseTurnSuggestionParams(params: unknown): TurnSuggestion | null {
    if (!params || typeof params !== 'object') {
        return null
    }
    const { turnIndex, kind, intent, confidence, title, description, scout, notebook } =
        params as PosthogTurnSuggestionParams
    if (typeof turnIndex !== 'number' || !Number.isInteger(turnIndex) || turnIndex < 0) {
        return null
    }
    if (kind !== 'scout' && kind !== 'notebook') {
        return null
    }
    const base = {
        turnIndex,
        intent: typeof intent === 'string' ? intent : 'unknown',
        confidence: typeof confidence === 'number' ? confidence : 0,
        title: nonEmptyString(title) ? title : FALLBACK_COPY[kind].title,
        description: nonEmptyString(description) ? description : FALLBACK_COPY[kind].description,
    }
    if (kind === 'scout') {
        const draft = parseScoutDraft(scout)
        return draft ? { ...base, kind, scout: draft } : null
    }
    const draft = parseNotebookDraft(notebook)
    return draft ? { ...base, kind, notebook: draft } : null
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

export interface ScoutCreateInput {
    suggestion: ScoutTurnSuggestion
    cadence: ScoutSuggestionCadence
    slackIntegrationId: number
    slackChannel: string
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
        },
    }
}
