import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import type { ScoutSuggestionExposure } from '../inboxAnalytics'

// pinned: storage key. Tabs share an SDK session, so they must also share its impressions.
const STORAGE_KEY = 'scout-suggestion-exposures'

interface ExposureStore {
    scope: string
    exposures: Record<string, ScoutSuggestionExposure>
}

let fallbackStore: ExposureStore | null = null

function readExposureStore(): ExposureStore {
    const scope = JSON.stringify([posthog.get_distinct_id(), posthog.get_session_id()])
    let exposures: ExposureStore['exposures'] = {}
    try {
        const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? 'null')
        if (
            stored?.scope === scope &&
            stored.exposures &&
            typeof stored.exposures === 'object' &&
            !Array.isArray(stored.exposures)
        ) {
            exposures = stored.exposures
        }
    } catch {
        // Blocked browser storage must not stop the card's actions or repeat its impression.
    }
    if (fallbackStore?.scope === scope) {
        exposures = { ...exposures, ...fallbackStore.exposures }
    }
    return { scope, exposures }
}

function readExposure(store: ExposureStore, key: string): ScoutSuggestionExposure | null {
    const exposure = store.exposures[key]
    return typeof exposure?.exposure_id === 'string' &&
        typeof exposure.batch_id === 'string' &&
        typeof exposure.suggestion_position === 'number'
        ? exposure
        : null
}

export function getScoutSuggestionExposure(
    batchId: string | null,
    suggestionId: string,
    position: number | null
): ScoutSuggestionExposure {
    return (
        (batchId ? readExposure(readExposureStore(), JSON.stringify([batchId, suggestionId])) : null) ?? {
            batch_id: batchId,
            exposure_id: null,
            suggestion_position: position,
        }
    )
}

export function recordScoutSuggestionExposure(
    batchId: string | null,
    suggestionId: string,
    position: number | null
): ScoutSuggestionExposure | null {
    if (!batchId || position === null) {
        return null
    }
    const store = readExposureStore()
    const key = JSON.stringify([batchId, suggestionId])
    if (readExposure(store, key)) {
        return null
    }
    const exposure: ScoutSuggestionExposure = {
        batch_id: batchId,
        exposure_id: uuidv4(),
        suggestion_position: position,
    }
    store.exposures[key] = exposure
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
    } catch {
        fallbackStore = store
    }
    return exposure
}
