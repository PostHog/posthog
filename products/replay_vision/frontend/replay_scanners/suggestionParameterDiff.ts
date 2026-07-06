import type { ReplayScannerPromptSuggestionApi } from '../generated/api.schemas'

export interface SamplingRateChange {
    before: number
    after: number
}

export interface SuggestionParameterChanges {
    tagsAdded: string[]
    tagsRemoved: string[]
    samplingRate: SamplingRateChange | null
    queryChanged: boolean
    /** Pretty-printed, key-sorted JSON of the recordings filter, for diff display. */
    queryBefore: string
    queryAfter: string
    /** Whether per-session behavior (scanner_config) differs; testing against rated sessions is pointless without it. */
    configChanged: boolean
}

function sortKeysDeep(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(sortKeysDeep)
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.keys(value)
                .sort()
                .map((key) => [key, sortKeysDeep((value as Record<string, unknown>)[key])])
        )
    }
    return value
}

/** Key-order-insensitive pretty JSON, so semantically equal objects from different sources don't read as a change. */
function stableJson(value: unknown): string {
    return JSON.stringify(sortKeysDeep(value ?? {}), null, 2)
}

function tagList(config: unknown): string[] {
    const tags = (config as { tags?: unknown } | null)?.tags
    return Array.isArray(tags) ? tags.filter((tag): tag is string => typeof tag === 'string') : []
}

/**
 * Non-prompt differences between the parameters a suggestion was generated against and the ones it
 * proposes. Null for suggestions generated before parameter proposals existed (prompt-only rows).
 */
export function suggestionParameterChanges(
    suggestion: Pick<ReplayScannerPromptSuggestionApi, 'base_parameters' | 'suggested_parameters'>
): SuggestionParameterChanges | null {
    const base = suggestion.base_parameters
    const suggested = suggestion.suggested_parameters
    if (!base || !suggested) {
        return null
    }
    const baseTags = tagList(base.scanner_config)
    const suggestedTags = tagList(suggested.scanner_config)
    const baseTagSet = new Set(baseTags)
    const suggestedTagSet = new Set(suggestedTags)
    const queryBefore = stableJson(base.query)
    const queryAfter = stableJson(suggested.query)
    return {
        tagsAdded: suggestedTags.filter((tag) => !baseTagSet.has(tag)),
        tagsRemoved: baseTags.filter((tag) => !suggestedTagSet.has(tag)),
        samplingRate:
            base.sampling_rate !== suggested.sampling_rate
                ? { before: base.sampling_rate, after: suggested.sampling_rate }
                : null,
        queryChanged: queryBefore !== queryAfter,
        queryBefore,
        queryAfter,
        configChanged: stableJson(base.scanner_config) !== stableJson(suggested.scanner_config),
    }
}

export function hasParameterChanges(changes: SuggestionParameterChanges): boolean {
    return (
        changes.tagsAdded.length > 0 ||
        changes.tagsRemoved.length > 0 ||
        changes.samplingRate !== null ||
        changes.queryChanged
    )
}
