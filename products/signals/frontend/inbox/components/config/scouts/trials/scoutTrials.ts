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
    submissions: ScoutTrialSubmission[]
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
    return {
        configId,
        contextId: null,
        submissions: variants.flatMap((variant) =>
            Array.from({ length: repeats }, (_, index) => ({
                request: {
                    launch_id: newId(),
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

export function trialReportText(document: Record<string, unknown>): string {
    for (const key of ['content', 'body', 'description', 'summary']) {
        if (typeof document[key] === 'string') {
            return document[key]
        }
    }
    return JSON.stringify(document, null, 2)
}
