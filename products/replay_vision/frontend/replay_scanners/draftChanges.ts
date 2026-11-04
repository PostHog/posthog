import { objectsEqual } from 'lib/utils/objects'

import type { ScannerFormValues } from './types'

/** The parts of an AI draft a person can change on review, named the way the review sections group them. */
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
        query: !objectsEqual(drafted.query ?? null, saved.query ?? null),
        sampling: drafted.sampling_mode !== saved.sampling_mode || drafted.sampling_rate !== saved.sampling_rate,
        model: drafted.model !== saved.model,
        budget:
            !!drafted.free_only !== !!saved.free_only ||
            !!drafted.credit_limit_enabled !== !!saved.credit_limit_enabled ||
            (drafted.credit_limit ?? null) !== (saved.credit_limit ?? null),
    }
    return (Object.keys(changed) as DraftChangedField[]).filter((field) => changed[field])
}
