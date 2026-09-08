import { getRuntimeAdapterForModel } from 'products/posthog_ai/frontend/utils/composerModels'

import type { ModelChoiceApi, TasksAIRunPreferencesApi } from '../generated/api.schemas'

/** A model/effort pick being edited in a settings UI; null model = inherit (no default stored). */
export interface AIRunPreferenceDraft {
    model: string | null
    reasoning_effort: string | null
}

export const EMPTY_DRAFT: AIRunPreferenceDraft = { model: null, reasoning_effort: null }

export interface DraftState {
    draft: AIRunPreferenceDraft
    touched: boolean
}

export const UNTOUCHED_EMPTY_DRAFT: DraftState = { draft: EMPTY_DRAFT, touched: false }

export function isDraftChanged(draft: AIRunPreferenceDraft, stored: AIRunPreferenceDraft): boolean {
    return draft.model !== stored.model || draft.reasoning_effort !== stored.reasoning_effort
}

export function draftFromStored(stored: TasksAIRunPreferencesApi | null | undefined): AIRunPreferenceDraft {
    return { model: stored?.model ?? null, reasoning_effort: stored?.reasoning_effort ?? null }
}

// The adapter is a property of the model, so it comes off the catalogue rather than the model id's
// spelling — the settings picker offers Codex models too, and a new harness must not be mislabelled.
export function payloadFromDraft(draft: AIRunPreferenceDraft, catalogue: ModelChoiceApi[]): TasksAIRunPreferencesApi {
    return {
        runtime_adapter: draft.model ? getRuntimeAdapterForModel(catalogue, draft.model) : null,
        model: draft.model,
        reasoning_effort: draft.model ? (draft.reasoning_effort as TasksAIRunPreferencesApi['reasoning_effort']) : null,
    }
}
