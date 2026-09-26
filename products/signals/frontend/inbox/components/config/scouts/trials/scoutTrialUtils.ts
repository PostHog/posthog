import type {
    ScoutTrialLaunchApi,
    ScoutTrialResultApi,
    ScoutTrialSetupApi,
} from 'products/signals/frontend/generated/api.schemas'

export const MAX_TRIAL_RUNS = 20

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
    error: string | null
}

export interface ScoutTrialBatch {
    configId: string
    contextId: string | null
    comparison: ScoutTrialComparison
    labels: Record<string, string>
    submissions: ScoutTrialSubmission[]
}

// Only these identifiers are persisted. Run content stays on the server.
export interface ScoutTrialComparison {
    id: string
    configId: string
    baselineVariantId: string
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

export function trialFormError(
    setup: ScoutTrialSetupApi | null,
    variants: ScoutTrialVariant[],
    repeats: number
): string | null {
    if (!setup?.ready) {
        return setup?.blocked_reason || 'Choose an available scout.'
    }
    if (!Number.isInteger(repeats) || repeats < 1 || variants.length * repeats > MAX_TRIAL_RUNS) {
        return `Choose between 1 and ${MAX_TRIAL_RUNS} total runs.`
    }
    if (variants.length < 1 || variants.some((variant) => !variant.label.trim())) {
        return 'Give every variant a name.'
    }
    if (new Set(variants.map((variant) => variant.label.trim())).size !== variants.length) {
        return 'Use a different name for each variant.'
    }
    for (const variant of variants) {
        const model = setup.models.find((option) => option.model === variant.model)
        if (!model?.reasoning_efforts.includes(variant.effort)) {
            return 'Choose a supported model and effort for every variant.'
        }
        if (variant.replacePrompt && !variant.prompt.trim()) {
            return 'Enter a replacement prompt or use the original prompt.'
        }
    }
    return null
}

export function initialTrialVariants(setup: ScoutTrialSetupApi): ScoutTrialVariant[] {
    const model = setup.models.find((option) => option.model === setup.model) ?? setup.models[0]
    const effort = model?.reasoning_efforts.includes(setup.reasoning_effort ?? '')
        ? setup.reasoning_effort!
        : model?.reasoning_efforts.includes('medium')
          ? 'medium'
          : (model?.reasoning_efforts[0] ?? '')
    return ['Baseline', 'Variant 1'].map((label, index) => ({
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
    newId: () => string
): ScoutTrialBatch {
    const groups = variants.map(() => ({
        variantId: newId(),
        launchIds: Array.from({ length: repeats }, () => newId()),
    }))
    return {
        configId,
        contextId: null,
        comparison: { id: newId(), configId, baselineVariantId: groups[0].variantId, groups },
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
                error: null,
            }))
        ),
    }
}

export function comparisonScoreDisabledReason(
    comparison: ScoutTrialComparison | null,
    results: Record<string, ScoutTrialResultApi>
): string | null {
    if (!comparison) {
        return 'Start or select a comparison first.'
    }
    const launches = comparison.groups.flatMap((group) => group.launchIds)
    if (launches.some((id) => !results[id] || results[id].status === 'unknown')) {
        return 'Every run in this comparison must have a confirmed result.'
    }
    if (launches.some((id) => results[id].status === 'not_started')) {
        return 'Some runs were not started. Retry their submissions or start a new comparison.'
    }
    if (
        launches.some(
            (id) =>
                !['completed', 'failed', 'cancelled', 'skipped'].includes(results[id].status) ||
                trialIsActive(results[id].task_status ?? '')
        )
    ) {
        return 'Wait for every run in this comparison to finish.'
    }
    return null
}

export function trialPercentage(value: number | null): string {
    return value === null ? 'Unavailable' : `${Math.round(value * 100)}%`
}

export function trialDelta(value: number | null): string {
    return value === null ? 'Not comparable' : `${value > 0 ? '+' : ''}${Math.round(value * 100)} pp`
}

export function trialReportText(document: Record<string, unknown>): string {
    for (const key of ['content', 'body', 'description', 'summary']) {
        if (typeof document[key] === 'string') {
            return document[key]
        }
    }
    return JSON.stringify(document, null, 2)
}
