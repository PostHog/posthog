import { getExperimentVariants } from 'scenes/experiments/utils'

import { NodeKind } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import type { ScannerExperimentTargetingApi } from 'products/replay_vision/frontend/generated/api.schemas'

import type { ReplayScanner } from './types'

/**
 * Experiment context a scanner is being created or edited against. Held by replayScannerLogic so
 * the Triggers step can offer variant targeting instead of raw filters. A null `variantKey` means
 * every variant of the experiment.
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
 * The scanner's persisted experiment targeting. The backend derives the person-scoped exposure
 * filter from this field at scan time — the same resolution the experiment Recordings tab uses —
 * so the scanner watches exactly the sessions that tab lists, including when the exposure event
 * fires server-side or in an earlier session. The exposure filter never enters `query` directly;
 * the API rejects it there so targeting stays behind this field's experiment access check.
 */
export function buildExperimentTargeting(context: ExperimentScannerContext): ScannerExperimentTargetingApi {
    return {
        experiment_id: context.experiment.id as number,
        variant: context.variantKey,
    }
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

/** Applies the experiment context to a fresh (or freshly templated) scanner: targeting, scoped name. */
export function prefillScannerForExperiment(scanner: ReplayScanner, context: ExperimentScannerContext): ReplayScanner {
    return {
        ...scanner,
        name: experimentScannerName(scanner.name, context.experiment.name),
        experiment_targeting: buildExperimentTargeting(context),
        query: {
            ...(scanner.query ?? { kind: NodeKind.RecordingsQuery }),
            filter_test_accounts: context.experiment.exposure_criteria?.filterTestAccounts ?? false,
        },
    }
}
