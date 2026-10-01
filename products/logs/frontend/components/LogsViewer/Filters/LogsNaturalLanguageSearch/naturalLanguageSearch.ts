import type { LogsNaturalLanguageQueryResponseApi } from 'products/logs/frontend/generated/api.schemas'

// Below this, the decision model is unsure enough that the person should pick the reading.
export const AUTO_APPLY_CONFIDENCE = 0.7

export const MIN_NATURAL_LANGUAGE_WORDS = 3

/** Whether the first candidate can be applied without asking the person to choose. */
export function shouldAutoApply(response: LogsNaturalLanguageQueryResponseApi): boolean {
    if (response.candidates.length === 1) {
        return true
    }
    return (
        response.candidates.length > 1 &&
        response.ranked_by === 'decision_model' &&
        (response.confidence ?? 0) >= AUTO_APPLY_CONFIDENCE
    )
}

/** Whether the search text reads like a sentence rather than a term to look up. */
export function looksLikeNaturalLanguage(searchQuery: string): boolean {
    return searchQuery.trim().split(/\s+/).filter(Boolean).length >= MIN_NATURAL_LANGUAGE_WORDS
}
