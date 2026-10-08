import { getExperimentVariants } from 'scenes/experiments/utils'

import { NodeKind, type RecordingsQuery } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import type { ScannerExperimentTargetingApi } from 'products/replay_vision/frontend/generated/api.schemas'

import type { ExperimentScannerConfig, ReplayScanner } from './types'

/**
 * Experiment context a scanner is being created or edited against. Held by replayScannerLogic so
 * the editor can name the experiment and offer its variants. A null `variantKey` means every
 * variant of the experiment.
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

export interface ScannerExperimentScope {
    experimentId: number
    /** Null watches every variant. */
    variants: string[] | null
}

/**
 * The experiment a scanner watches, wherever it is stored. The experiment type keeps it in
 * `scanner_config`; older types use `experiment_targeting`. Mirrors the backend's `experiment_scope()`.
 */
export function scannerExperimentScope(scanner: ReplayScanner | null | undefined): ScannerExperimentScope | null {
    if (!scanner) {
        return null
    }
    if (scanner.scanner_type === 'experiment') {
        const { experiment_id, variants } = scanner.scanner_config
        return experiment_id ? { experimentId: experiment_id, variants: variants ?? null } : null
    }
    const targeting = scanner.experiment_targeting
    if (!targeting?.experiment_id) {
        return null
    }
    return { experimentId: targeting.experiment_id, variants: targeting.variant ? [targeting.variant] : null }
}

/** The variants a scope watches, as a short phrase: "test variant", "a, b variants", or the fallback. */
export function scopeVariantsLabel(scope: ScannerExperimentScope, everyVariant: string): string {
    if (!scope.variants?.length) {
        return everyVariant
    }
    return `${scope.variants.join(', ')} ${scope.variants.length === 1 ? 'variant' : 'variants'}`
}

/**
 * The query keys an experiment-scoped scanner takes from its experiment. The population is never
 * one of them: the API derives it from the experiment at scan time, and rejects an exposure filter
 * set here.
 * Every entry point that creates such a scanner reads this, so the test-account default cannot
 * drift between them.
 */
export function experimentScannerQuery(experiment: Experiment): Pick<RecordingsQuery, 'kind' | 'filter_test_accounts'> {
    return {
        kind: NodeKind.RecordingsQuery,
        filter_test_accounts: experiment.exposure_criteria?.filterTestAccounts ?? false,
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

/**
 * The default focus for an experiment scanner's summaries. The variant keys are deliberately
 * absent: the scan reads each session's variant from exposure data, and a prompt that names them
 * invites the model to guess one instead. The experiment's name and hypothesis are absent too: each
 * scan adds them after an access check, and a saved prompt shows them to anyone who can view the
 * scanner, including people who cannot view the experiment.
 */
export const EXPERIMENT_SCANNER_PROMPT = [
    'Summarize what this participant did after the point where the experiment change would first be visible to them. Ignore anything earlier in the session.',
    "Use the experiment's name and hypothesis, which every scan includes, to work out which part of the product it changes.",
    'If they never reached the part of the product the experiment changes, say so in one sentence.',
    'Otherwise describe how they used it: where they moved on without trouble, where they paused or went back, what they seemed to misread, and any error or dead end they hit.',
].join('\n\n')

/** The experiment type's config for an experiment, with every variant sampled evenly by default. */
export function experimentScannerConfig(
    experiment: Experiment,
    variants: string[] | null,
    prompt: string = EXPERIMENT_SCANNER_PROMPT
): ExperimentScannerConfig {
    return {
        prompt,
        length: 'medium',
        experiment_id: experiment.id as number,
        variants,
        balance_variants: true,
    }
}

/**
 * Legacy experiment targeting on another scanner type, for teams without the experiment type yet. The
 * backend derives the person-scoped exposure filter from it at scan time.
 */
export function buildExperimentTargeting(context: ExperimentScannerContext): ScannerExperimentTargetingApi {
    return {
        experiment_id: context.experiment.id as number,
        variant: context.variantKey,
    }
}

/**
 * Turns a fresh (or freshly templated) scanner into an experiment scanner for the context: the
 * experiment type, a scoped name, and the experiment's test-account setting. A template's type and
 * prompt give way, because only the experiment type compares variants.
 */
export function prefillScannerForExperiment(
    scanner: ReplayScanner,
    context: ExperimentScannerContext,
    asExperimentScanner: boolean
): ReplayScanner {
    const query = { ...scanner.query, ...experimentScannerQuery(context.experiment) }
    if (!asExperimentScanner) {
        return {
            ...scanner,
            name: experimentScannerName(scanner.name, context.experiment.name),
            experiment_targeting: buildExperimentTargeting(context),
            query,
        }
    }
    return {
        ...scanner,
        name: experimentScannerName(scanner.name, context.experiment.name),
        scanner_type: 'experiment',
        scanner_config: experimentScannerConfig(context.experiment, context.variantKey ? [context.variantKey] : null),
        experiment_targeting: null,
        query,
    }
}
