import type { SignalScoutCreateApi } from 'products/signals/frontend/generated/api.schemas'

import type { ScoutSuggestionCadence, TurnSuggestion } from '../types/streamTypes'
import type { PosthogTurnSuggestionParams } from '../types/wireTypes'

const CADENCES: readonly ScoutSuggestionCadence[] = ['daily', 'weekly']

export const CADENCE_OPTIONS: { value: ScoutSuggestionCadence; label: string }[] = [
    { value: 'daily', label: 'Every day' },
    { value: 'weekly', label: 'Every week' },
]

function isCadence(value: unknown): value is ScoutSuggestionCadence {
    return typeof value === 'string' && (CADENCES as readonly string[]).includes(value)
}

function nonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value.trim().length > 0
}

/** Narrows a `_posthog/turn_suggestion` frame; anything the card cannot act on is dropped. */
export function parseTurnSuggestionParams(params: unknown): TurnSuggestion | null {
    if (!params || typeof params !== 'object') {
        return null
    }
    const { turnIndex, kind, intent, confidence, title, description, scout } = params as PosthogTurnSuggestionParams
    if (kind !== 'scout' || typeof turnIndex !== 'number' || !Number.isInteger(turnIndex) || turnIndex < 0) {
        return null
    }
    if (!scout || !nonEmptyString(scout.displayName) || !nonEmptyString(scout.body) || !isCadence(scout.cadence)) {
        return null
    }
    return {
        turnIndex,
        kind: 'scout',
        intent: typeof intent === 'string' ? intent : 'unknown',
        confidence: typeof confidence === 'number' ? confidence : 0,
        title: nonEmptyString(title) ? title : 'Turn this into a scout',
        description: nonEmptyString(description)
            ? description
            : 'Run this analysis on a schedule and post the results to Slack.',
        scout: {
            displayName: scout.displayName,
            description: nonEmptyString(scout.description) ? scout.description : '',
            body: scout.body,
            cadence: scout.cadence,
        },
    }
}

/** Five-field cron in the project timezone: 09:00 every day, or 09:00 every Monday. */
export function cadenceToCron(cadence: ScoutSuggestionCadence): string {
    return cadence === 'daily' ? '0 9 * * *' : '0 9 * * 1'
}

export function cadenceLabel(cadence: ScoutSuggestionCadence): string {
    return cadence === 'daily' ? 'every day' : 'every week'
}

/** The channel picker stores `CHANNEL_ID|#name`; the name half is what the card shows back. */
export function slackChannelDisplayName(channel: string): string {
    const [, name] = channel.split('|')
    return name || channel
}

export interface ScoutCreateInput {
    suggestion: TurnSuggestion
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
