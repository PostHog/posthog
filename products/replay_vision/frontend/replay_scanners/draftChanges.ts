import { objectsEqual } from 'lib/utils/objects'

import type { ScannerCreationMethodEnumApi } from '../generated/api.schemas'
import { DEFAULT_MODEL, OBSERVATION_CREDITS_BY_MODEL, type ScannerFormValues } from './types'

export type DraftChangedField =
    | 'name'
    | 'description'
    | 'prompt'
    | 'scanner_type'
    | 'type_config'
    | 'query'
    | 'sampling'
    | 'model'
    | 'budget'

function configWithoutPrompt(scanner: ScannerFormValues): object {
    if (!scanner.scanner_config) {
        return {}
    }
    const { prompt: _prompt, ...rest } = scanner.scanner_config
    return rest
}

/** Which parts of the drafted form the person changed before saving. Empty when they saved the draft as drafted. */
export function draftChanges(drafted: ScannerFormValues, saved: ScannerFormValues): DraftChangedField[] {
    const changed: Record<DraftChangedField, boolean> = {
        name: (drafted.name ?? '').trim() !== (saved.name ?? '').trim(),
        description: (drafted.description ?? '').trim() !== (saved.description ?? '').trim(),
        prompt: (drafted.scanner_config?.prompt ?? '').trim() !== (saved.scanner_config?.prompt ?? '').trim(),
        scanner_type: drafted.scanner_type !== saved.scanner_type,
        type_config: !objectsEqual(configWithoutPrompt(drafted), configWithoutPrompt(saved)),
        query:
            !objectsEqual(drafted.query ?? null, saved.query ?? null) ||
            !objectsEqual(drafted.experiment_targeting ?? null, saved.experiment_targeting ?? null),
        sampling: drafted.sampling_mode !== saved.sampling_mode || drafted.sampling_rate !== saved.sampling_rate,
        model: drafted.model !== saved.model,
        budget:
            !!drafted.free_only !== !!saved.free_only ||
            !!drafted.credit_limit_enabled !== !!saved.credit_limit_enabled ||
            (drafted.credit_limit ?? null) !== (saved.credit_limit ?? null),
    }
    return (Object.keys(changed) as DraftChangedField[]).filter((field) => changed[field])
}

export type ModelChangeDirection = 'unchanged' | 'upgrade' | 'downgrade' | 'same_price'

export interface ScannerModelChoice {
    initial_model_source: 'ai_draft' | 'default' | 'unknown'
    initial_model: string | null
    model: string
    model_changed: boolean | null
    model_change_direction: ModelChangeDirection | null
}

function creditsFor(model: string): number | undefined {
    return OBSERVATION_CREDITS_BY_MODEL[model as keyof typeof OBSERVATION_CREDITS_BY_MODEL]
}

/** The model the form offered before the person touched it, against the one they saved. An upgrade costs
 * more per observation. An AI draft without a recorded baseline leaves the offered model unknown. */
export function scannerModelChoice(
    creationMethod: ScannerCreationMethodEnumApi,
    goalDraftBaseline: ScannerFormValues | null,
    savedModel: string
): ScannerModelChoice {
    const source = creationMethod !== 'ai' ? 'default' : goalDraftBaseline ? 'ai_draft' : 'unknown'
    const initialModel = source === 'default' ? DEFAULT_MODEL : (goalDraftBaseline?.model ?? null)
    if (initialModel == null) {
        return {
            initial_model_source: source,
            initial_model: null,
            model: savedModel,
            model_changed: null,
            model_change_direction: null,
        }
    }
    const initialCredits = creditsFor(initialModel)
    const savedCredits = creditsFor(savedModel)
    let direction: ModelChangeDirection | null = 'unchanged'
    if (initialModel !== savedModel) {
        direction =
            initialCredits == null || savedCredits == null
                ? null
                : savedCredits > initialCredits
                  ? 'upgrade'
                  : savedCredits < initialCredits
                    ? 'downgrade'
                    : 'same_price'
    }
    return {
        initial_model_source: source,
        initial_model: initialModel,
        model: savedModel,
        model_changed: initialModel !== savedModel,
        model_change_direction: direction,
    }
}
