import { objectsEqual } from 'lib/utils/objects'

import type {
    DraftFieldEnumApi,
    RefineScannerDraftCurrentApi,
    RefineScannerDraftResponseApi,
} from '../generated/api.schemas'
import { type ScannerExperimentScope, scannerExperimentScope } from './experimentTargeting'
import type { ScannerConfig, ScannerFormValues } from './types'

/** The parts of a draft, as the refine endpoint reports them changed. */
export type DraftChangedField = DraftFieldEnumApi

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

/** The recordings a draft watches: its filter and the experiment it is scoped to. */
export interface DraftRecordings {
    query: ScannerFormValues['query'] | null
    experiment: ScannerExperimentScope | null
}

export function draftRecordings(scanner: ScannerFormValues): DraftRecordings {
    return { query: scanner.query ?? null, experiment: scannerExperimentScope(scanner) }
}

/** Whether the person changed the recordings the AI drafted. Unknown counts as changed, so a refine never replaces them. */
export function recordingsEdited(drafted: DraftRecordings | null, scanner: ScannerFormValues): boolean {
    return !drafted || !objectsEqual(drafted, draftRecordings(scanner))
}

/** Whether the form's credit limit is on, read the way the editor reads it: a limit without the toggle counts as on. */
export function creditLimitOn(scanner: ScannerFormValues): boolean {
    return scanner.credit_limit_enabled ?? scanner.credit_limit != null
}

/** The form as the refine endpoint reads it: the create body's shape, with the limit only when it is on. */
export function refineCurrentDraft(scanner: ScannerFormValues): RefineScannerDraftCurrentApi {
    return {
        name: scanner.name,
        description: scanner.description ?? '',
        scanner_type: scanner.scanner_type,
        scanner_config: scanner.scanner_config,
        query: scanner.query ?? null,
        sampling_mode: scanner.sampling_mode,
        sampling_rate: scanner.sampling_rate,
        model: scanner.model,
        credit_limit: creditLimitOn(scanner) ? (scanner.credit_limit ?? null) : null,
        free_only: !!scanner.free_only,
    } as RefineScannerDraftCurrentApi
}

/** Applies the type and config a refine changed. A new type replaces the whole config, so no setting of the old type is left behind. */
function applyRefinedConfig(
    next: ScannerFormValues,
    refined: RefineScannerDraftResponseApi,
    changed: Set<DraftChangedField>
): void {
    const refinedConfig = refined.scanner_config as ScannerConfig
    if (changed.has('scanner_type') || changed.has('type_config')) {
        next.scanner_type = refined.scanner_type as ScannerFormValues['scanner_type']
        next.scanner_config = {
            ...refinedConfig,
            prompt: changed.has('prompt') ? refinedConfig.prompt : next.scanner_config.prompt,
        } as ScannerConfig
    } else if (changed.has('prompt')) {
        next.scanner_config = { ...next.scanner_config, prompt: refinedConfig.prompt } as ScannerConfig
    }
}

/** Applies the recordings, sampling and model a refine changed. */
function applyRefinedDials(
    next: ScannerFormValues,
    refined: RefineScannerDraftResponseApi,
    changed: Set<DraftChangedField>
): void {
    if (changed.has('query')) {
        // A null query is the model clearing the filter ("watch every recording"), not a missing one.
        next.query = (refined.query ?? null) as ScannerFormValues['query']
    }
    if (changed.has('sampling') && refined.sampling_mode && refined.sampling_rate != null) {
        next.sampling_mode = refined.sampling_mode as ScannerFormValues['sampling_mode']
        next.sampling_rate = refined.sampling_rate
    }
    if (changed.has('model') && refined.model) {
        next.model = refined.model as ScannerFormValues['model']
    }
}

/** The form with only the refine's changed fields applied, so a manual edit to any other field survives. */
export function refinedFormValues(
    scanner: ScannerFormValues,
    refined: RefineScannerDraftResponseApi
): ScannerFormValues {
    const changed = new Set(refined.changed_fields)
    const next: ScannerFormValues = { ...scanner }
    if (changed.has('name')) {
        next.name = refined.name
    }
    if (changed.has('description')) {
        next.description = refined.description
    }
    applyRefinedConfig(next, refined, changed)
    applyRefinedDials(next, refined, changed)
    if (changed.has('budget')) {
        next.free_only = refined.free_only
        next.credit_limit = refined.credit_limit ?? null
        next.credit_limit_enabled = refined.credit_limit != null
    }
    return next
}
