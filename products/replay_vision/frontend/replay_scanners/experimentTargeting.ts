import { getExposureFallbackFilter, getViewRecordingFiltersForVariant } from 'scenes/experiments/utils'
import { convertUniversalFiltersToRecordingsQuery } from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { DEFAULT_RECORDING_FILTERS } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { Experiment, FilterLogicalOperator, UniversalFiltersGroupValue } from '~/types'

import type { ReplayScanner } from './types'

/**
 * Experiment context a scanner is being created against. Held by replayScannerLogic for the
 * lifetime of the wizard so the Triggers step can offer variant targeting instead of raw filters.
 * An empty `variantKeys` means every variant of the experiment.
 */
export interface ExperimentScannerContext {
    experiment: Experiment
    variantKeys: string[]
    /**
     * When the experiment's default exposure event is captured server-side (no `$session_id`),
     * the entry point passes this so the scanner filters on `$feature/<flag_key>` instead of an
     * exposure event that can never match a recording. Mirrors the experiment Recordings tab's
     * fallback behavior; the linkability check already ran there, so the deep link carries the
     * answer rather than re-running it here.
     */
    useExposureFallback: boolean
}

export interface ExperimentScannerParams {
    experimentId: number
    variantKeys: string[]
    useExposureFallback: boolean
}

/** Builds the search params an entry point appends to a new-scanner wizard URL. */
export function experimentScannerParams(params: ExperimentScannerParams): Record<string, string> {
    const result: Record<string, string> = { experiment: String(params.experimentId) }
    if (params.variantKeys.length > 0) {
        result.variants = params.variantKeys.join(',')
    }
    if (params.useExposureFallback) {
        result.exposure = 'fallback'
    }
    return result
}

/** Reads the experiment context params off a wizard URL. Null when the URL carries none. */
export function parseExperimentScannerParams(searchParams: Record<string, any>): ExperimentScannerParams | null {
    const experimentId = Number(searchParams.experiment)
    if (!Number.isInteger(experimentId) || experimentId <= 0) {
        return null
    }
    const variantsRaw = searchParams.variants
    const variantKeys =
        typeof variantsRaw === 'string' && variantsRaw.length > 0
            ? variantsRaw
                  .split(',')
                  .map((key) => key.trim())
                  .filter(Boolean)
            : []
    return { experimentId, variantKeys, useExposureFallback: searchParams.exposure === 'fallback' }
}

/**
 * The exposure filter for the selected variants, in the same shape the experiment Recordings tab
 * uses, so a scanner watches exactly the sessions that tab lists.
 */
export function buildExperimentExposureFilter(
    experiment: Experiment,
    variantKeys: string[],
    useExposureFallback: boolean
): UniversalFiltersGroupValue | null {
    const variantArg = variantKeys.length > 0 ? variantKeys : undefined
    if (useExposureFallback) {
        // Null only for custom exposure configs, which carry semantics a flag-value filter can't
        // stand in for; those keep the real exposure filter below.
        const fallback = getExposureFallbackFilter(experiment, variantArg)
        if (fallback) {
            return fallback
        }
    }
    return getViewRecordingFiltersForVariant(experiment, variantArg)[0] ?? null
}

/**
 * A scanner `query` targeting the experiment's selected variants. The exposure filter is the
 * first (and only) leaf so the Triggers step can later swap it when the variant selection
 * changes without touching filters the user added by hand.
 */
export function buildExperimentScannerQuery(
    experiment: Experiment,
    variantKeys: string[],
    useExposureFallback: boolean
): RecordingsQuery {
    const exposureFilter = buildExperimentExposureFilter(experiment, variantKeys, useExposureFallback)
    const converted = convertUniversalFiltersToRecordingsQuery({
        ...DEFAULT_RECORDING_FILTERS,
        filter_test_accounts: experiment.exposure_criteria?.filterTestAccounts ?? false,
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: exposureFilter ? [exposureFilter] : [],
                },
            ],
        },
    })
    // Only the dimensions the Triggers editor persists; the rest (dates, order, session ids) are
    // playlist concerns the scanner model strips or never stores.
    return {
        kind: converted.kind,
        events: converted.events,
        actions: converted.actions,
        properties: converted.properties,
        console_log_filters: converted.console_log_filters,
        having_predicates: converted.having_predicates,
        comment_text: converted.comment_text,
        filter_test_accounts: converted.filter_test_accounts,
        operand: converted.operand,
    }
}

/** Scanner name for an experiment-scoped scanner, within the model's 255-char limit. */
export function experimentScannerName(baseName: string, experimentName: string): string {
    const name = baseName ? `${baseName}: ${experimentName}` : experimentName
    return name.slice(0, 255)
}

/** Applies the experiment context to a fresh (or freshly templated) scanner: targeted query, scoped name. */
export function prefillScannerForExperiment(scanner: ReplayScanner, context: ExperimentScannerContext): ReplayScanner {
    return {
        ...scanner,
        name: experimentScannerName(scanner.name, context.experiment.name),
        query: buildExperimentScannerQuery(context.experiment, context.variantKeys, context.useExposureFallback),
    }
}
