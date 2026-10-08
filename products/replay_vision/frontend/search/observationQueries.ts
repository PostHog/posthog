import { combineUrl } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Breadcrumb } from '~/types'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { ReplayScannerTab } from '../replay_scanners/replayScannerSceneLogic'
import { parseCitedSegments, stripCitations } from '../utils/citations'
import { readModelOutput, readTitle } from '../utils/observation'

const SIMILAR_QUERY_MAX_CHARS = 300

export function firstCitedTimestampMs(observation: ReplayObservationApi): number | null {
    const result = readModelOutput(observation)
    if (!result) {
        return null
    }
    for (const [textKey, segmentsKey] of [
        ['summary', 'summary_segments'],
        ['reasoning', 'reasoning_segments'],
    ] as const) {
        const text = result[textKey]
        if (typeof text !== 'string') {
            continue
        }
        const chip = parseCitedSegments(text, result[segmentsKey]).find((segment) => segment.kind === 'chip')
        if (chip && chip.kind === 'chip' && chip.timestamp_ms >= 0) {
            return chip.timestamp_ms
        }
    }
    return null
}

export function similarSearchQuery(observation: ReplayObservationApi): string | null {
    const result = readModelOutput(observation)
    if (!result) {
        return null
    }
    const summary = typeof result.summary === 'string' ? stripCitations(result.summary, result.summary_segments) : ''
    const reasoning =
        typeof result.reasoning === 'string' ? stripCitations(result.reasoning, result.reasoning_segments) : ''
    const text = [readTitle(observation), summary || reasoning].filter(Boolean).join(' ')
    if (!text) {
        return null
    }
    if (text.length <= SIMILAR_QUERY_MAX_CHARS) {
        return text
    }
    const cut = text.slice(0, SIMILAR_QUERY_MAX_CHARS)
    const lastSpace = cut.lastIndexOf(' ')
    // A cut inside a surrogate pair would make encodeURIComponent throw.
    return (lastSpace > 0 ? cut.slice(0, lastSpace) : cut.replace(/[\uD800-\uDBFF]$/, '')).trim()
}

export function searchTabUrl(params: Record<string, string> = {}): string {
    return combineUrl(urls.replayVision(), { tab: ReplayScannerTab.Search, ...params }).url
}

export function searchReturnParams(
    searchedQuery: string,
    scannerId: string | null,
    sourceObservationId: string | null
): Record<string, string> {
    return {
        tab: ReplayScannerTab.Search,
        ...(scannerId ? { scanner: scannerId } : {}),
        ...(sourceObservationId ? { similar: sourceObservationId } : searchedQuery ? { q: searchedQuery } : {}),
    }
}

export function searchBreadcrumb(returnParams: Record<string, string>): Breadcrumb {
    const { tab: _tab, ...params } = returnParams
    return { key: 'search', name: 'Search', path: searchTabUrl(params) }
}

const SIMILAR_SEARCH_INTENT_KEY = 'replay-vision.similar-search-intent'

// Both logics are mounted app-wide. `values` throws if not, where `findMounted` would silently mismatch owners.
function intentOwner(): string {
    return `${userLogic.values.user?.uuid ?? ''}:${teamLogic.values.currentTeamId ?? ''}`
}

/** The query travels through sessionStorage, not the URL: it is observation prose that can carry customer
 * names, so it must stay out of $current_url and browser history. It is bound to the user who armed it. */
export function similarSearchUrl(observation: ReplayObservationApi): string | null {
    return similarSearchQuery(observation) ? searchTabUrl({ similar: observation.id }) : null
}

export function markSimilarSearchIntent(observation: ReplayObservationApi): void {
    try {
        sessionStorage.setItem(
            SIMILAR_SEARCH_INTENT_KEY,
            JSON.stringify({
                query: similarSearchQuery(observation),
                sourceObservationId: observation.id,
                owner: intentOwner(),
            })
        )
    } catch {
        // No storage: the hub opens on its empty state.
    }
}

export function readSimilarSearchIntent(sourceObservationId: string): string | null {
    try {
        const raw = sessionStorage.getItem(SIMILAR_SEARCH_INTENT_KEY)
        const parsed = raw ? JSON.parse(raw) : null
        return parsed?.sourceObservationId === sourceObservationId &&
            parsed.owner === intentOwner() &&
            typeof parsed.query === 'string'
            ? parsed.query
            : null
    } catch {
        return null
    }
}
