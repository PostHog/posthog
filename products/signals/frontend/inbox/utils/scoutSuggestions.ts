import { describeCron } from 'lib/cron'

import type {
    ScoutSuggestionItemApi,
    ScoutSuggestionProposedConfigApi,
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

/** A custom draft as the create form's starting point, so the person sees it before it runs. */
export function suggestionToCreateValues(item: ScoutSuggestionItemApi): ScoutCreateInitialValues {
    return {
        name: item.skill_name,
        description: item.description,
        body: item.draft_body,
        config: {
            emit: item.proposed_config.emit,
            run_cron_schedule: item.proposed_config.run_cron_schedule ?? null,
            run_interval_minutes: item.proposed_config.run_interval_minutes ?? DEFAULT_SUGGESTION_INTERVAL_MINUTES,
        },
        suggestionId: item.id,
    }
}
