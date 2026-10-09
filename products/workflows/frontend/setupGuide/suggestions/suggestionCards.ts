import type {
    DataSuggestionApi,
    DataSuggestionStageEnumApi,
    DataSuggestionStepKindEnumApi,
} from '../../generated/api.schemas'

export type SuggestionStepKind = DataSuggestionStepKindEnumApi

/** One suggested workflow card, written by the AI from the project's events. */
export interface SuggestionCard {
    key: string
    stage: DataSuggestionStageEnumApi
    title: string
    description: string
    triggerEvent: string
    weeklyCount: number
    steps: SuggestionStepKind[]
    suggestionId: string
}

export function cardFromSuggestion(suggestion: DataSuggestionApi): SuggestionCard {
    return {
        key: `ai-${suggestion.id}`,
        stage: suggestion.stage,
        title: suggestion.name,
        description: suggestion.description,
        triggerEvent: suggestion.trigger_event,
        weeklyCount: suggestion.weekly_count,
        steps: suggestion.step_outline,
        suggestionId: suggestion.id,
    }
}
