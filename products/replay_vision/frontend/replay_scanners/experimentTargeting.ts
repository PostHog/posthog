import { getExperimentVariants } from 'scenes/experiments/utils'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import type { ReplayScanner } from './types'

/**
 * Experiment context a scanner is being created against. Held by replayScannerLogic for the
 * lifetime of the wizard so the Triggers step can offer variant targeting instead of raw filters.
 * A null `variantKey` means every variant of the experiment.
 */
export interface ExperimentScannerContext {
    experiment: Experiment
    variantKey: string | null
}

export interface ExperimentScannerParams {
    experimentId: number
    variantKey: string | null
}

/** Builds the search params an entry point appends to a new-scanner wizard URL. */
export function experimentScannerParams(params: ExperimentScannerParams): Record<string, string> {
    const result: Record<string, string> = { experiment: String(params.experimentId) }
    if (params.variantKey) {
        result.variant = params.variantKey
    }
    return result
}

/** Reads the experiment context params off a wizard URL. Null when the URL carries none. */
export function parseExperimentScannerParams(searchParams: Record<string, any>): ExperimentScannerParams | null {
    const experimentRaw = searchParams.experiment
    // kea-router coerces `?experiment=true` to boolean `true`, and `Number(true)` is 1, which would
    // pass the check below and silently prefill experiment 1. Only a string or number is a real id.
    if (typeof experimentRaw !== 'string' && typeof experimentRaw !== 'number') {
        return null
    }
    const experimentId = Number(experimentRaw)
    if (!Number.isInteger(experimentId) || experimentId <= 0) {
        return null
    }
    // kea-router coerces `?variant=1` to the number 1, so stringify.
    const variantRaw = searchParams.variant
    const variantKey =
        typeof variantRaw === 'string' || typeof variantRaw === 'number' ? String(variantRaw).trim() || null : null
    return { experimentId, variantKey }
}

/**
 * The scanner `query` targeting the experiment's exposed persons. Exposure is resolved server-side
 * from the experiment (person-scoped), the same way the experiment Recordings tab resolves it, so
 * the scanner watches exactly the sessions that tab lists — including when the exposure event fires
 * server-side or in an earlier session.
 */
export function buildExperimentScannerQuery(experiment: Experiment, variantKey: string | null): RecordingsQuery {
    return {
        kind: 'RecordingsQuery',
        filter_test_accounts: experiment.exposure_criteria?.filterTestAccounts ?? false,
        experiment_exposure: {
            experiment_id: experiment.id as number,
            ...(variantKey ? { variant: variantKey } : {}),
        },
    } as RecordingsQuery
}

/**
 * Applies `variantKey` to an existing scanner query, keeping every other filter the user added.
 * Person-scoped exposure lives in `experiment_exposure`, not the filter group, so a variant change
 * only rewrites that one field.
 */
export function applyExperimentVariant(
    query: RecordingsQuery | null,
    context: ExperimentScannerContext
): RecordingsQuery {
    return {
        ...(query ?? { kind: 'RecordingsQuery' }),
        experiment_exposure: {
            experiment_id: context.experiment.id as number,
            ...(context.variantKey ? { variant: context.variantKey } : {}),
        },
    } as RecordingsQuery
}

/**
 * Keeps the requested variant key only if the loaded experiment actually has it. A URL can carry a
 * stale `?variant=old-key`, which would target a variant that no longer exists; dropping it falls
 * back to all variants (null) rather than persisting an impossible target.
 */
export function reconcileVariantKey(experiment: Experiment, requestedKey: string | null): string | null {
    if (requestedKey === null) {
        return null
    }
    const known = new Set(getExperimentVariants(experiment).map((variant) => variant.key))
    return known.has(requestedKey) ? requestedKey : null
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
        query: buildExperimentScannerQuery(context.experiment, context.variantKey),
    }
}
