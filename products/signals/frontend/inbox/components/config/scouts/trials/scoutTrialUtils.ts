import type {
    ScoutTrialComparisonApi,
    ScoutTrialComparisonRequestApi,
    ScoutTrialLaunchApi,
    ScoutTrialResultApi,
    ScoutTrialSetupApi,
} from 'products/signals/frontend/generated/api.schemas'

export const MAX_TRIAL_VARIANTS = 20
export const MAX_TRIAL_REPEATS = 20

export interface ScoutTrialVariant {
    id: string
    label: string
    model: string
    effort: string
    replacePrompt: boolean
    prompt: string
}

export interface TrackedScoutTrial {
    configId: string
    launchId: string
}

export interface ScoutTrialSubmission {
    request: ScoutTrialLaunchApi
    accepted: boolean
}

export interface ScoutTrialBatch {
    configId: string
    comparison: ScoutTrialComparison
    request: ScoutTrialComparisonRequestApi
    labels: Record<string, string>
    submissions: ScoutTrialSubmission[]
}

// Only these identifiers are persisted. Run content stays on the server.
export interface ScoutTrialComparison {
    id: string
    configId: string
    baselineVariantId: string
    sourceEvaluationId?: string
    groups: { variantId: string; launchIds: string[] }[]
}

export interface ScoutTrialRow {
    launchId: string
    variant: string
    model: string
    effort: string
    status: string
    startedAt: string | null
    error: string | null
    result: ScoutTrialResultApi | null
}

export function trialIsActive(status: string): boolean {
    return ['pending', 'running', 'queued', 'in_progress', 'starting'].includes(status)
}

export function comparisonIsActive(status: string): boolean {
    return ['starting', 'running', 'judging'].includes(status)
}

export function comparisonIdentifiers(comparison: ScoutTrialComparisonApi): ScoutTrialComparison {
    return {
        id: comparison.comparison_id,
        configId: comparison.config_id,
        baselineVariantId: comparison.baseline_variant_id,
        groups: comparison.variants.map((variant) => ({ variantId: variant.id, launchIds: variant.launch_ids })),
    }
}

export function trialTaskIsActive(status: string | null | undefined): boolean {
    return !!status && ['not_started', 'queued', 'in_progress'].includes(status)
}

export function trialFormError(
    setup: ScoutTrialSetupApi | null,
    variants: ScoutTrialVariant[],
    repeats: number
): string | null {
    if (!setup?.ready) {
        return setup?.blocked_reason || 'Choose an available scout.'
    }
    if (!Number.isInteger(repeats) || repeats < 1 || repeats > MAX_TRIAL_REPEATS) {
        return `Choose between 1 and ${MAX_TRIAL_REPEATS} runs per version.`
    }
    if (variants.length < 2 || variants.length > MAX_TRIAL_VARIANTS) {
        return `Use between 2 and ${MAX_TRIAL_VARIANTS} versions per trial.`
    }
    if (variants.some((variant) => !variant.label.trim())) {
        return 'Give every version a name.'
    }
    if (new Set(variants.map((variant) => variant.label.trim())).size !== variants.length) {
        return 'Use a different name for each version.'
    }
    for (const variant of variants) {
        const model = setup.models.find((option) => option.model === variant.model)
        if (!model?.reasoning_efforts.includes(variant.effort)) {
            return 'Choose a supported model and effort for every version.'
        }
        if (variant.replacePrompt && !variant.prompt.trim()) {
            return 'Enter a replacement prompt or use the original prompt.'
        }
    }
    return null
}

export function initialTrialVariants(setup: ScoutTrialSetupApi): ScoutTrialVariant[] {
    // Blank instead of a default, so a baseline that differs from the source scout is an explicit choice.
    const model = setup.models.find((option) => option.model === setup.model)
    const effort =
        setup.reasoning_effort && model?.reasoning_efforts.includes(setup.reasoning_effort)
            ? setup.reasoning_effort
            : ''
    return ['Baseline', 'Version B'].map((label, index) => ({
        id: String(index),
        label,
        model: model?.model ?? '',
        effort,
        replacePrompt: false,
        prompt: '',
    }))
}

export function createTrialBatch(
    configId: string,
    variants: ScoutTrialVariant[],
    repeats: number,
    note: string,
    newId: () => string,
    expectedSkillVersion?: number
): ScoutTrialBatch {
    const groups = variants.map(() => ({
        variantId: newId(),
        launchIds: Array.from({ length: repeats }, () => newId()),
    }))
    const comparisonId = newId()
    return {
        configId,
        comparison: { id: comparisonId, configId, baselineVariantId: groups[0].variantId, groups },
        request: {
            comparison_id: comparisonId,
            ...(expectedSkillVersion !== undefined ? { expected_skill_version: expectedSkillVersion } : {}),
            baseline_variant_id: groups[0].variantId,
            variants: variants.map((variant, index) => ({
                id: groups[index].variantId,
                label: variant.label.trim(),
                launch_ids: groups[index].launchIds,
                model: variant.model,
                reasoning_effort: variant.effort,
                ...(variant.replacePrompt ? { skill_body: variant.prompt } : {}),
            })),
            ...(note.trim() ? { note: note.trim() } : {}),
        },
        labels: Object.fromEntries(groups.map((group, index) => [group.variantId, variants[index].label.trim()])),
        submissions: variants.flatMap((variant, variantIndex) =>
            Array.from({ length: repeats }, (_, index) => ({
                request: {
                    launch_id: groups[variantIndex].launchIds[index],
                    variant: repeats > 1 ? `${variant.label.trim()} (${index + 1})` : variant.label.trim(),
                    model: variant.model,
                    reasoning_effort: variant.effort,
                    ...(note.trim() ? { note: note.trim() } : {}),
                    ...(variant.replacePrompt ? { skill_body: variant.prompt } : {}),
                },
                accepted: false,
            }))
        ),
    }
}

export function comparisonScoreDisabledReason(
    comparison: ScoutTrialComparison | null,
    results: Record<string, ScoutTrialResultApi>
): string | null {
    if (!comparison) {
        return 'Start or select a trial first.'
    }
    const launches = comparison.groups.flatMap((group) => group.launchIds)
    if (launches.some((id) => !results[id] || results[id].status === 'unknown')) {
        return 'Every run in this trial must have a confirmed result.'
    }
    if (launches.some((id) => results[id].status === 'not_started')) {
        return 'Some runs were not started. Retry their submissions or start a new trial.'
    }
    if (
        launches.some(
            (id) =>
                !['completed', 'failed', 'cancelled', 'skipped'].includes(results[id].status) ||
                trialTaskIsActive(results[id].task_status)
        )
    ) {
        return 'Wait for every run in this trial to finish.'
    }
    return null
}

export function trialPercentage(value: number | null): string {
    return value === null ? 'Unavailable' : `${Math.round(value * 100)}%`
}

export function trialReportText(document: Record<string, unknown>): string {
    for (const key of ['content', 'body', 'description', 'summary']) {
        if (typeof document[key] === 'string') {
            return document[key]
        }
    }
    return JSON.stringify(document, null, 2)
}
