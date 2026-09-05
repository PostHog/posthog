import { describeCron } from 'lib/cron'

import type {
    ScoutSuggestionItemApi,
    ScoutSuggestionProposedConfigApi,
    SignalScoutConfigApi,
} from 'products/signals/frontend/generated/api.schemas'

import type { ScoutCreateInitialValues } from '../logics/scoutCreateModalLogic'
import { dailyCronToTime, formatRunIntervalShort } from './scoutRunsWindow'

/** Minutes between runs a suggestion that names no schedule of its own would be created with. */
export const DEFAULT_SUGGESTION_INTERVAL_MINUTES = 1440

/** How often the suggested scout would run, in the roster's own words. */
export function suggestionCadenceLabel(config: ScoutSuggestionProposedConfigApi): string {
    if (config.run_cron_schedule) {
        const dailyTime = dailyCronToTime(config.run_cron_schedule)
        return dailyTime ? `daily at ${dailyTime}` : (describeCron(config.run_cron_schedule)?.toLowerCase() ?? 'daily')
    }
    return formatRunIntervalShort(config.run_interval_minutes ?? DEFAULT_SUGGESTION_INTERVAL_MINUTES)
}

/** The card's one-line summary of what the scout would do: how often, and where its output goes. */
export function suggestionMetaLine(config: ScoutSuggestionProposedConfigApi): string {
    const output = config.emit ? 'files reports to the inbox' : 'dry run, files nothing'
    return `Runs ${suggestionCadenceLabel(config)} · ${output}`
}

/** The scout a canonical pick would turn on, as it exists on the project. */
export interface ExistingScoutForSuggestion {
    config: SignalScoutConfigApi
    description: string
    body: string
}

/**
 * A suggestion as the create form's starting point, so the person sees it before it runs. A custom
 * draft brings its own text; a canonical pick shows the existing scout's, and submitting turns that
 * scout on rather than creating one.
 */
export function suggestionToCreateValues(
    item: ScoutSuggestionItemApi,
    existing: ExistingScoutForSuggestion | null = null
): ScoutCreateInitialValues {
    const proposed = item.proposed_config
    const proposesSchedule = !!proposed.run_cron_schedule || proposed.run_interval_minutes !== null
    const schedule = {
        run_cron_schedule: proposed.run_cron_schedule ?? null,
        run_interval_minutes: proposed.run_interval_minutes ?? DEFAULT_SUGGESTION_INTERVAL_MINUTES,
    }
    if (existing) {
        // The pick proposes when the scout runs, and a pick that names no cadence leaves the
        // scout's own. Everything else the config already holds is the person's own: the emit
        // posture, the Slack destination, tags and servers stay as they are, shown in the form so
        // turning the scout on cannot quietly restore delivery it had before.
        const { config } = existing
        return {
            name: item.skill_name,
            description: existing.description,
            body: existing.body,
            existingConfigId: config.id,
            config: {
                ...(proposesSchedule
                    ? schedule
                    : {
                          run_cron_schedule: config.run_cron_schedule,
                          run_interval_minutes: config.run_interval_minutes,
                      }),
                emit: config.emit,
                output_destinations: config.output_destinations,
                tags: config.tags ?? [],
                mcp_gateway_server_ids: [...config.mcp_gateway_server_ids],
            },
            suggestionId: item.id,
        }
    }
    return {
        name: item.skill_name,
        description: item.description,
        body: item.draft_body,
        config: { ...schedule, emit: item.proposed_config.emit },
        suggestionId: item.id,
    }
}
