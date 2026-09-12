import { MakeLogicType, actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api-error'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { signalsReportsRetrieve, signalsScoutScratchpadSearch } from 'products/signals/frontend/generated/api'
import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

import { SCOUT_ROSTER_WINDOW_HOURS, isPipelineWriter } from '../utils/scoutRunsWindow'
import { BOOKKEEPING_KINDS, isReportUuid, scratchpadKindOf, scratchpadTopicOf } from '../utils/scratchpadKeys'

// Search reruns the server-side ILIKE on every keystroke; debounce so typing doesn't
// fire a request per character.
const SEARCH_DEBOUNCE_MS = 300
// `list` caps at 1000 newest-first with no pagination wrapper — pull the whole window in
// one read and filter it client-side. Older memory arrives through `loadOlderEntries`, which
// walks the endpoint's `date_to` cursor a page at a time.
export const SCRATCHPAD_FETCH_LIMIT = 1000
// Bodies are an unbounded TextField clamped at 50k chars on write, so a full-fat window of
// 1000 entries is a payload nobody needs: the ledger renders a one-line clamp until you open it.
// Pull previews for the list and fetch the one body you expand. Sized well past one line so
// the overwhelming majority of notes arrive complete and never need the second read.
export const SCRATCHPAD_PREVIEW_CHARS = 1200
// Rows per ledger page. Sized so the report-title resolution below covers the first page or two.
export const SCRATCHPAD_PAGE_SIZE = 25
/**
 * How many report titles the panel resolves per pass. Keys namespaced by a report UUID need that
 * report's title to read as anything, but the reports endpoint has no bulk-by-id filter, so each
 * one costs a request. Cap the pass at the rows a reader can actually see; everything past it
 * falls back to the shortened UUID until it scrolls into a later pass.
 */
const REPORT_TITLE_RESOLVE_CAP = 30

/** The time spans the ledger can ask the endpoint for, mapped to `date_from`. */
export type ScratchpadTimeFilter = 'window' | '1h' | '24h' | '7d' | '30d'

const TIME_FILTER_HOURS: Record<Exclude<ScratchpadTimeFilter, 'window'>, number> = {
    '1h': 1,
    '24h': 24,
    '7d': 24 * 7,
    '30d': 24 * 30,
}

/** The `date_from` bound a time filter asks the endpoint for, or nothing for the default window. */
function dateFromParam(timeFilter: ScratchpadTimeFilter): { date_from?: string } {
    if (timeFilter === 'window') {
        return {}
    }
    return { date_from: dayjs().subtract(TIME_FILTER_HOURS[timeFilter], 'hour').toISOString() }
}

/** The header's headline numbers over the loaded window. */
export interface ScratchpadWindowStats {
    scouts: number
    topics: number
    expiringSoon: number
}

/** One option in the scout, kind or topic multi-select: the raw value and how many rows carry it. */
export interface ScratchpadFacet {
    value: string
    count: number
}

/** Whether a listed entry's body may have been cut short by the preview projection. The API
 * truncates with a bare slice and sends no "there's more" marker, so preview-length is the only
 * signal available. A body sitting exactly on the boundary re-fetches once and resolves to the
 * same text, which is why this is the cheap direction to be wrong in. */
export function isPreviewTruncated(content: string | null | undefined): boolean {
    return (content?.length ?? 0) >= SCRATCHPAD_PREVIEW_CHARS
}

/**
 * The notes one scout wrote, newest first. The search endpoint has no per-scout filter, but every
 * entry carries the skill that created it, so the scout page narrows the already-loaded project
 * window rather than issuing a second read. Always fed the unfiltered `entries`, never search
 * results: a scout's memory shouldn't shrink because someone typed in the fleet search box.
 */
export function entriesForSkill(entries: ScratchpadEntryApi[] | null, skillName: string): ScratchpadEntryApi[] {
    return (entries ?? []).filter((entry) => entry.created_by_skill === skillName)
}

/**
 * How wide a span the loaded rows actually cover, e.g. "last 8 h". The header needs this because
 * 1,000 rows is a cap, not a total: on a busy project the window closes after a few hours, and a
 * bare "1,000 entries" reads as the whole memory.
 */
export function describeLoadedSpan(entries: ScratchpadEntryApi[] | null): string | null {
    const stamps = (entries ?? []).map((entry) => entry.updated_at).filter((stamp): stamp is string => !!stamp)
    if (stamps.length === 0) {
        return null
    }
    const oldest = dayjs(stamps[stamps.length - 1])
    const hours = dayjs().diff(oldest, 'hour')
    if (hours < 1) {
        return 'last hour'
    }
    if (hours < 48) {
        return `last ${hours} h`
    }
    return `last ${Math.round(hours / 24)} days`
}

/** Counts of each distinct value across the rows, most common first, blanks dropped. */
function facetsOf(
    entries: ScratchpadEntryApi[],
    valueOf: (entry: ScratchpadEntryApi) => string | null
): ScratchpadFacet[] {
    const counts = new Map<string, number>()
    for (const entry of entries) {
        const value = valueOf(entry)
        if (value) {
            counts.set(value, (counts.get(value) ?? 0) + 1)
        }
    }
    return [...counts.entries()]
        .map(([value, count]) => ({ value, count }))
        .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value))
}

/** Whether an entry passes the scout, kind and topic multi-selects. The bookkeeping switch is not
 * part of this because the footer counts the rows that switch would hide, so the count has to see
 * them. */
function matchesFacetFilters(
    entry: ScratchpadEntryApi,
    scoutFilter: string[],
    kindFilter: string[],
    topicFilter: string[]
): boolean {
    if (scoutFilter.length > 0 && !scoutFilter.includes(entry.created_by_skill ?? '')) {
        return false
    }
    const kind = scratchpadKindOf(entry.key)
    if (kindFilter.length > 0 && (kind === null || !kindFilter.includes(kind))) {
        return false
    }
    const topic = scratchpadTopicOf(entry.key)
    if (topicFilter.length > 0 && (topic === null || !topicFilter.includes(topic))) {
        return false
    }
    return true
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scratchpadLogicValues {
    canLoadOlderEntries: boolean
    entries: ScratchpadEntryApi[] | null
    entriesLoading: boolean
    expandedKeys: string[]
    filteredEntries: ScratchpadEntryApi[] | null
    fullContentByKey: Record<string, string>
    hasActiveFilters: boolean
    hasMoreOlderEntries: boolean
    hideBookkeeping: boolean
    kindFacets: ScratchpadFacet[]
    kindFilter: string[]
    loadFailed: boolean
    loadedSpanLabel: string | null
    loadingContentKeys: string[]
    olderEntries: ScratchpadEntryApi[]
    olderEntriesFailed: boolean
    olderEntriesLoading: boolean
    recentlyLearnedCount: number
    recentlyLearnedCountCapped: boolean
    reportTitles: Record<string, string | null>
    scoutFacets: ScratchpadFacet[]
    scoutFilter: string[]
    searchFailed: boolean
    searchResults: ScratchpadEntryApi[] | null
    searchResultsLoading: boolean
    searchText: string
    timeFilter: ScratchpadTimeFilter
    topicFacets: ScratchpadFacet[]
    topicFilter: string[]
    totalCount: number | null
    unresolvedReportIds: string[]
    visibleBookkeepingCount: number
    visibleEntries: ScratchpadEntryApi[] | null
    windowEntries: ScratchpadEntryApi[] | null
    windowGeneration: number
    windowStats: ScratchpadWindowStats
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scratchpadLogicActions {
    appendOlderEntries: (
        entries: ScratchpadEntryApi[],
        hasMore: boolean
    ) => {
        entries: ScratchpadEntryApi[]
        hasMore: boolean
    }
    clearFilters: () => {}
    loadEntries: (_payload: void) => void
    loadEntriesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadEntriesSuccess: (
        entries: ScratchpadEntryApi[],
        payload?: void
    ) => {
        entries: ScratchpadEntryApi[]
        payload?: void
    }
    loadFullContent: (key: string) => {
        key: string
    }
    loadFullContentFailure: (key: string) => {
        key: string
    }
    loadFullContentSuccess: (
        key: string,
        content: string
    ) => {
        content: string
        key: string
    }
    loadOlderEntries: () => {}
    loadOlderEntriesFailure: () => {}
    loadSearchResults: (_payload: void) => void
    loadSearchResultsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSearchResultsSuccess: (
        searchResults: ScratchpadEntryApi[] | null,
        payload?: void
    ) => {
        searchResults: ScratchpadEntryApi[] | null
        payload?: void
    }
    resolveReportTitles: () => {}
    setHideBookkeeping: (hideBookkeeping: boolean) => {
        hideBookkeeping: boolean
    }
    setKindFilter: (kindFilter: string[]) => {
        kindFilter: string[]
    }
    setReportTitle: (
        reportId: string,
        title: string | null
    ) => {
        reportId: string
        title: string | null
    }
    setScoutFilter: (scoutFilter: string[]) => {
        scoutFilter: string[]
    }
    setSearchText: (searchText: string) => {
        searchText: string
    }
    setTimeFilter: (timeFilter: ScratchpadTimeFilter) => {
        timeFilter: ScratchpadTimeFilter
    }
    setTopicFilter: (topicFilter: string[]) => {
        topicFilter: string[]
    }
    toggleEntry: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scratchpadLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        windowEntries: (
            entries: ScratchpadEntryApi[] | null,
            olderEntries: ScratchpadEntryApi[]
        ) => ScratchpadEntryApi[] | null
        totalCount: (windowEntries: ScratchpadEntryApi[] | null) => number | null
        loadedSpanLabel: (windowEntries: ScratchpadEntryApi[] | null) => string | null
        canLoadOlderEntries: (hasMoreOlderEntries: boolean, searchText: string) => boolean
        recentlyLearnedCount: (entries: ScratchpadEntryApi[] | null) => number
        recentlyLearnedCountCapped: (entries: ScratchpadEntryApi[] | null, recentlyLearnedCount: number) => boolean
        visibleEntries: (
            windowEntries: ScratchpadEntryApi[] | null,
            searchResults: ScratchpadEntryApi[] | null,
            searchText: string
        ) => ScratchpadEntryApi[] | null
        scoutFacets: (visibleEntries: ScratchpadEntryApi[] | null) => ScratchpadFacet[]
        kindFacets: (visibleEntries: ScratchpadEntryApi[] | null) => ScratchpadFacet[]
        topicFacets: (visibleEntries: ScratchpadEntryApi[] | null) => ScratchpadFacet[]
        windowStats: (windowEntries: ScratchpadEntryApi[] | null) => ScratchpadWindowStats
        visibleBookkeepingCount: (
            visibleEntries: ScratchpadEntryApi[] | null,
            scoutFilter: string[],
            kindFilter: string[],
            topicFilter: string[]
        ) => number
        hasActiveFilters: (
            scoutFilter: string[],
            kindFilter: string[],
            topicFilter: string[],
            hideBookkeeping: boolean,
            searchText: string,
            timeFilter: ScratchpadTimeFilter
        ) => boolean
        filteredEntries: (
            visibleEntries: ScratchpadEntryApi[] | null,
            scoutFilter: string[],
            kindFilter: string[],
            topicFilter: string[],
            hideBookkeeping: boolean
        ) => ScratchpadEntryApi[] | null
        unresolvedReportIds: (
            filteredEntries: ScratchpadEntryApi[] | null,
            reportTitles: Record<string, string | null>
        ) => string[]
    }
}

export type scratchpadLogicType = MakeLogicType<
    scratchpadLogicValues,
    scratchpadLogicActions,
    Record<string, any>,
    scratchpadLogicMeta
>

/**
 * Read-only view over the scout fleet's durable memory (`SignalScratchpad`). Owns the loaded
 * window, the debounced search text (wired straight to the endpoint's `?text=` ILIKE), the
 * client-side ledger filters, and the report titles that make UUID-namespaced keys readable.
 * There is no write surface on purpose — humans inspect this memory; only the harness
 * (internal-scope) writes it.
 *
 * `entries` is always the unfiltered first page: the roster's "learned" headline and the scout
 * page's memory panel read it, and neither a search nor a ledger filter may shrink those. A
 * search lands in `searchResults`, older pages land in `olderEntries`, and the ledger reads
 * `filteredEntries` on top of whichever applies.
 */
export const scratchpadLogic = kea<scratchpadLogicType>([
    path(['scenes', 'inbox', 'logics', 'scratchpadLogic']),

    actions({
        setSearchText: (searchText: string) => ({ searchText }),
        setScoutFilter: (scoutFilter: string[]) => ({ scoutFilter }),
        setKindFilter: (kindFilter: string[]) => ({ kindFilter }),
        setTopicFilter: (topicFilter: string[]) => ({ topicFilter }),
        setTimeFilter: (timeFilter: ScratchpadTimeFilter) => ({ timeFilter }),
        setHideBookkeeping: (hideBookkeeping: boolean) => ({ hideBookkeeping }),
        clearFilters: () => ({}),
        toggleEntry: (key: string) => ({ key }),
        loadFullContent: (key: string) => ({ key }),
        loadFullContentSuccess: (key: string, content: string) => ({ key, content }),
        loadFullContentFailure: (key: string) => ({ key }),
        loadOlderEntries: () => ({}),
        appendOlderEntries: (entries: ScratchpadEntryApi[], hasMore: boolean) => ({ entries, hasMore }),
        loadOlderEntriesFailure: () => ({}),
        resolveReportTitles: () => ({}),
        setReportTitle: (reportId: string, title: string | null) => ({ reportId, title }),
    }),

    loaders(({ values }) => ({
        entries: [
            null as ScratchpadEntryApi[] | null,
            {
                loadEntries: async (_payload: void, breakpoint) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const page = await signalsScoutScratchpadSearch(String(teamId), {
                        limit: SCRATCHPAD_FETCH_LIMIT,
                        content_max_chars: SCRATCHPAD_PREVIEW_CHARS,
                        ...dateFromParam(values.timeFilter),
                    })
                    // Drop a stale response if the span moved on while this request was in flight.
                    // A wider span is the slower read, so narrowing right after widening is the
                    // order that would otherwise let the older response answer last.
                    breakpoint()
                    return page
                },
            },
        ],
        searchResults: [
            null as ScratchpadEntryApi[] | null,
            {
                loadSearchResults: async (_payload: void, breakpoint) => {
                    const teamId = teamLogic.values.currentTeamId
                    const text = values.searchText.trim()
                    if (!teamId || !text) {
                        return null
                    }
                    const results = await signalsScoutScratchpadSearch(String(teamId), {
                        text,
                        limit: SCRATCHPAD_FETCH_LIMIT,
                        content_max_chars: SCRATCHPAD_PREVIEW_CHARS,
                        ...dateFromParam(values.timeFilter),
                    })
                    // Drop a stale response if the search moved on while this request was in flight.
                    breakpoint()
                    return results
                },
            },
        ],
    })),

    reducers({
        searchText: ['', { setSearchText: (_, { searchText }) => searchText, clearFilters: () => '' }],
        scoutFilter: [[] as string[], { setScoutFilter: (_, { scoutFilter }) => scoutFilter, clearFilters: () => [] }],
        kindFilter: [[] as string[], { setKindFilter: (_, { kindFilter }) => kindFilter, clearFilters: () => [] }],
        topicFilter: [[] as string[], { setTopicFilter: (_, { topicFilter }) => topicFilter, clearFilters: () => [] }],
        timeFilter: [
            'window' as ScratchpadTimeFilter,
            { setTimeFilter: (_, { timeFilter }) => timeFilter, clearFilters: () => 'window' as ScratchpadTimeFilter },
        ],
        // Whether to drop the scouts' self-bookkeeping. Off by default — a first-time reader should
        // see everything the fleet writes — but a reader who turns it off keeps it off.
        hideBookkeeping: [
            false,
            { persist: true },
            {
                setHideBookkeeping: (_, { hideBookkeeping }) => hideBookkeeping,
                // The switch counts towards `hasActiveFilters`, which is what puts the clear
                // button on screen, so the clear has to reach it. Otherwise a window of nothing
                // but bookkeeping rows renders the same empty state after every press.
                clearFilters: () => false,
            },
        ],
        // Did the most recent load reject? Lets the panel tell a failed load apart from an empty
        // project (kea-loaders leaves `entries` at its prior value on failure, so it can't).
        loadFailed: [
            false,
            {
                loadEntries: () => false,
                loadEntriesSuccess: () => false,
                loadEntriesFailure: () => true,
            },
        ],
        searchFailed: [
            false,
            {
                loadSearchResults: () => false,
                loadSearchResultsSuccess: () => false,
                loadSearchResultsFailure: () => true,
            },
        ],
        // Clearing the box drops the last result set at once, so the unfiltered window shows
        // without waiting on the debounce.
        searchResults: [
            null as ScratchpadEntryApi[] | null,
            {
                setSearchText: (state, { searchText }) => (searchText.trim() ? state : null),
                clearFilters: () => null,
            },
        ],
        // Which first page the walked pages belong to. A page read against an earlier window can
        // still answer after a reload started, and this is bumped at dispatch, so the listener
        // sees the invalidation without waiting for the fresh page to arrive.
        windowGeneration: [0, { loadEntries: (state: number) => state + 1 }],
        // Pages walked back past the 1,000-row cap with the endpoint's `date_to` cursor. A fresh
        // first page invalidates them: it may already carry rows these pages hold.
        olderEntries: [
            [] as ScratchpadEntryApi[],
            {
                appendOlderEntries: (state, { entries }) => [...state, ...entries],
                loadEntries: () => [],
            },
        ],
        olderEntriesLoading: [
            false,
            {
                loadOlderEntries: () => true,
                appendOlderEntries: () => false,
                loadOlderEntriesFailure: () => false,
                loadEntries: () => false,
            },
        ],
        // Did the last older-page request reject? A page that succeeds can also append nothing,
        // once the dedupe below drops every row it carried, so an unchanged list cannot stand in
        // for a failure and the footer has to be told.
        olderEntriesFailed: [
            false,
            {
                loadOlderEntries: () => false,
                appendOlderEntries: () => false,
                loadOlderEntriesFailure: () => true,
                loadEntries: () => false,
            },
        ],
        // Is there anything past what's loaded? A first page that came back short has already
        // reached the end of the memory, so the load-older button stays hidden.
        hasMoreOlderEntries: [
            false,
            {
                loadEntriesSuccess: (_, { entries }) => entries.length >= SCRATCHPAD_FETCH_LIMIT,
                appendOlderEntries: (_, { hasMore }) => hasMore,
                // A reload drops the walked pages, so the control goes with them until the fresh
                // first page says whether anything older is left.
                loadEntries: () => false,
            },
        ],
        // Which entry rows are open. Lives here rather than in the table's own state so the
        // listener below can hang the full-body fetch off the same toggle.
        expandedKeys: [
            [] as string[],
            {
                toggleEntry: (state, { key }) =>
                    state.includes(key) ? state.filter((k) => k !== key) : [...state, key],
            },
        ],
        // Full bodies fetched on expand, keyed by entry key. Dropped on every reload of the window,
        // which may carry newer bodies for the same keys.
        fullContentByKey: [
            {} as Record<string, string>,
            {
                loadFullContentSuccess: (state, { key, content }) => ({ ...state, [key]: content }),
                loadEntriesSuccess: () => ({}),
            },
        ],
        loadingContentKeys: [
            [] as string[],
            {
                loadFullContent: (state, { key }) => (state.includes(key) ? state : [...state, key]),
                loadFullContentSuccess: (state, { key }) => state.filter((k) => k !== key),
                loadFullContentFailure: (state, { key }) => state.filter((k) => k !== key),
                loadEntriesSuccess: () => [],
            },
        ],
        // Report titles for UUID-namespaced keys. A null means the lookup came back empty — the
        // report is gone — and stops the key being asked for again.
        reportTitles: [
            {} as Record<string, string | null>,
            {
                setReportTitle: (state, { reportId, title }) => ({ ...state, [reportId]: title }),
            },
        ],
    }),

    selectors({
        // Everything loaded, newest first: the first page plus any older pages walked after it.
        windowEntries: [
            (s) => [s.entries, s.olderEntries],
            (entries: ScratchpadEntryApi[] | null, olderEntries: ScratchpadEntryApi[]): ScratchpadEntryApi[] | null =>
                entries === null ? null : [...entries, ...olderEntries],
        ],
        totalCount: [
            (s) => [s.windowEntries],
            (windowEntries: ScratchpadEntryApi[] | null): number | null =>
                windowEntries ? windowEntries.length : null,
        ],
        loadedSpanLabel: [
            (s) => [s.windowEntries],
            (windowEntries: ScratchpadEntryApi[] | null): string | null => describeLoadedSpan(windowEntries),
        ],
        /**
         * Whether the load-older control has a page to fetch. The cursor walks the unfiltered
         * window, and a search is a separate one-shot read that the appended pages never reach, so
         * the control has nothing to offer a reader who is searching.
         */
        canLoadOlderEntries: [
            (s) => [s.hasMoreOlderEntries, s.searchText],
            (hasMoreOlderEntries: boolean, searchText: string): boolean => hasMoreOlderEntries && !searchText.trim(),
        ],
        // Entries written or refreshed over the roster window, so the roster's "learned" headline
        // sits on the same span as the run and report numbers the summary endpoint returns for it.
        recentlyLearnedCount: [
            (s) => [s.entries],
            (entries: ScratchpadEntryApi[] | null): number => {
                if (!entries) {
                    return 0
                }
                const windowStart = dayjs().subtract(SCOUT_ROSTER_WINDOW_HOURS, 'hours')
                return entries.filter((entry) => entry.updated_at && dayjs(entry.updated_at).isAfter(windowStart))
                    .length
            },
        ],
        // Every fetched entry fell inside the window and the fetch hit its cap, so the real count is
        // higher than the one shown.
        recentlyLearnedCountCapped: [
            (s) => [s.entries, s.recentlyLearnedCount],
            (entries: ScratchpadEntryApi[] | null, recentlyLearnedCount: number): boolean =>
                entries !== null && entries.length >= SCRATCHPAD_FETCH_LIMIT && recentlyLearnedCount === entries.length,
        ],
        // What the ledger filters over: the search hits while a search is typed, the whole loaded
        // window otherwise. Null while the applicable set is still loading.
        visibleEntries: [
            (s) => [s.windowEntries, s.searchResults, s.searchText],
            (
                windowEntries: ScratchpadEntryApi[] | null,
                searchResults: ScratchpadEntryApi[] | null,
                searchText: string
            ): ScratchpadEntryApi[] | null => (searchText.trim() ? searchResults : windowEntries),
        ],
        scoutFacets: [
            (s) => [s.visibleEntries],
            (visibleEntries: ScratchpadEntryApi[] | null): ScratchpadFacet[] =>
                facetsOf(visibleEntries ?? [], (entry) => entry.created_by_skill ?? null),
        ],
        kindFacets: [
            (s) => [s.visibleEntries],
            (visibleEntries: ScratchpadEntryApi[] | null): ScratchpadFacet[] =>
                facetsOf(visibleEntries ?? [], (entry) => scratchpadKindOf(entry.key)),
        ],
        topicFacets: [
            (s) => [s.visibleEntries],
            (visibleEntries: ScratchpadEntryApi[] | null): ScratchpadFacet[] =>
                facetsOf(visibleEntries ?? [], (entry) => scratchpadTopicOf(entry.key)),
        ],
        /**
         * The header's three counts. All read the loaded window rather than the filtered rows: the
         * header says what is loaded and over what span, and a search that matches nothing must not
         * make it read as though the fleet has no scouts.
         *
         * Expiry is the one property that changes what a row means without anyone touching it, so
         * it gets counted rather than left to a reader to notice.
         */
        windowStats: [
            (s) => [s.windowEntries],
            (windowEntries: ScratchpadEntryApi[] | null): ScratchpadWindowStats => {
                const horizon = dayjs().add(7, 'day')
                const entries = windowEntries ?? []
                return {
                    scouts: new Set(
                        entries
                            .map((entry) => entry.created_by_skill)
                            .filter((skillName): skillName is string => !!skillName && !isPipelineWriter(skillName))
                    ).size,
                    topics: new Set(entries.map((entry) => scratchpadTopicOf(entry.key)).filter(Boolean)).size,
                    expiringSoon: entries.filter(
                        (entry) => entry.expires_at && dayjs(entry.expires_at).isBefore(horizon)
                    ).length,
                }
            },
        ],
        /**
         * The bookkeeping rows among the listed ones, because the footer prints this number as a
         * share of the rows the table shows. The hide-bookkeeping switch is left out on purpose:
         * while it is off, the number says how many rows it would drop, and the footer hides the
         * line while it is on.
         */
        visibleBookkeepingCount: [
            (s) => [s.visibleEntries, s.scoutFilter, s.kindFilter, s.topicFilter],
            (
                visibleEntries: ScratchpadEntryApi[] | null,
                scoutFilter: string[],
                kindFilter: string[],
                topicFilter: string[]
            ): number =>
                (visibleEntries ?? []).filter((entry) => {
                    const kind = scratchpadKindOf(entry.key)
                    return (
                        kind !== null &&
                        BOOKKEEPING_KINDS.has(kind) &&
                        matchesFacetFilters(entry, scoutFilter, kindFilter, topicFilter)
                    )
                }).length,
        ],
        hasActiveFilters: [
            (s) => [s.scoutFilter, s.kindFilter, s.topicFilter, s.hideBookkeeping, s.searchText, s.timeFilter],
            (
                scoutFilter: string[],
                kindFilter: string[],
                topicFilter: string[],
                hideBookkeeping: boolean,
                searchText: string,
                timeFilter: ScratchpadTimeFilter
            ): boolean =>
                scoutFilter.length > 0 ||
                kindFilter.length > 0 ||
                topicFilter.length > 0 ||
                hideBookkeeping ||
                searchText.trim().length > 0 ||
                timeFilter !== 'window',
        ],
        // The rows the ledger lists. Newest-first order comes from the endpoint and is preserved.
        filteredEntries: [
            (s) => [s.visibleEntries, s.scoutFilter, s.kindFilter, s.topicFilter, s.hideBookkeeping],
            (
                visibleEntries: ScratchpadEntryApi[] | null,
                scoutFilter: string[],
                kindFilter: string[],
                topicFilter: string[],
                hideBookkeeping: boolean
            ): ScratchpadEntryApi[] | null => {
                if (visibleEntries === null) {
                    return null
                }
                return visibleEntries.filter((entry) => {
                    if (!matchesFacetFilters(entry, scoutFilter, kindFilter, topicFilter)) {
                        return false
                    }
                    const kind = scratchpadKindOf(entry.key)
                    return !(hideBookkeeping && kind !== null && BOOKKEEPING_KINDS.has(kind))
                })
            },
        ],
        // Report UUIDs on screen whose title hasn't been looked up yet, newest first and capped.
        unresolvedReportIds: [
            (s) => [s.filteredEntries, s.reportTitles],
            (filteredEntries: ScratchpadEntryApi[] | null, reportTitles: Record<string, string | null>): string[] => {
                const ids: string[] = []
                for (const entry of filteredEntries ?? []) {
                    const topic = scratchpadTopicOf(entry.key)
                    if (topic && isReportUuid(topic) && !Object.hasOwn(reportTitles, topic) && !ids.includes(topic)) {
                        ids.push(topic)
                        if (ids.length >= REPORT_TITLE_RESOLVE_CAP) {
                            break
                        }
                    }
                }
                return ids
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        setSearchText: async ({ searchText }, breakpoint) => {
            if (!searchText.trim()) {
                return
            }
            await breakpoint(SEARCH_DEBOUNCE_MS)
            actions.loadSearchResults()
        },

        // The time span is the one filter the endpoint applies, so changing it reloads rather than
        // narrowing what's already here — a wider span has rows the loaded window never held.
        setTimeFilter: () => {
            actions.loadEntries()
            if (values.searchText.trim()) {
                actions.loadSearchResults()
            }
        },

        // Clearing resets the span through a reducer, and the span is the one filter the endpoint
        // applies, so the loaded rows can still be a narrowed response. Refetch rather than only
        // reset the control: the select reads as the default span after the reset, so picking that
        // span again fires nothing and the reader has no way back to the full window.
        clearFilters: () => {
            actions.loadEntries()
        },

        loadEntriesSuccess: () => {
            actions.resolveReportTitles()
        },

        loadSearchResultsSuccess: () => {
            actions.resolveReportTitles()
        },

        appendOlderEntries: () => {
            actions.resolveReportTitles()
        },

        // Walk one page further back with the endpoint's `date_to` cursor. Exclusive upper bound,
        // so the oldest loaded row's own timestamp is the right cursor and never repeats it.
        loadOlderEntries: async () => {
            const teamId = teamLogic.values.currentTeamId
            const loaded = values.windowEntries ?? []
            const cursor = loaded[loaded.length - 1]?.updated_at
            const generation = values.windowGeneration
            if (!teamId || !cursor) {
                actions.loadOlderEntriesFailure()
                return
            }
            try {
                const page = await signalsScoutScratchpadSearch(String(teamId), {
                    limit: SCRATCHPAD_FETCH_LIMIT,
                    content_max_chars: SCRATCHPAD_PREVIEW_CHARS,
                    date_to: cursor,
                    ...dateFromParam(values.timeFilter),
                })
                // The window this page was cursored from is gone if a reload started meanwhile.
                // Appending would file its rows under a different first page, and the dedupe below
                // was built from the old window, so it cannot drop keys the new page carries.
                if (values.windowGeneration !== generation) {
                    return
                }
                // Rows sharing the cursor timestamp fall outside an exclusive bound, so a page can
                // still carry a key already on screen. Keys are unique per team, so drop by key.
                const seen = new Set(loaded.map((entry) => entry.key))
                actions.appendOlderEntries(
                    page.filter((entry) => !seen.has(entry.key)),
                    page.length >= SCRATCHPAD_FETCH_LIMIT
                )
            } catch {
                actions.loadOlderEntriesFailure()
            }
        },

        // Opening a row is the only moment a full body is worth fetching — and only when the
        // preview actually cut one off. Collapsing, re-opening a cached entry, or opening a note
        // that arrived whole all stay local.
        toggleEntry: ({ key }) => {
            if (!values.expandedKeys.includes(key)) {
                return
            }
            // `hasOwn`, not `in`: keys are scout-authored, and `'toString' in {}` is true.
            if (Object.hasOwn(values.fullContentByKey, key) || values.loadingContentKeys.includes(key)) {
                return
            }
            // A row can sit in either list (the scout page renders from the window while a search
            // may still be typed in the panel), so look in both.
            const entry = [...(values.windowEntries ?? []), ...(values.searchResults ?? [])].find((e) => e.key === key)
            if (entry && isPreviewTruncated(entry.content)) {
                actions.loadFullContent(key)
            }
        },

        // Deliberately no `breakpoint()`: kea's is per-action, not per-key, so opening a second
        // note would unwind the first request mid-flight and strand its key in
        // `loadingContentKeys` — a row stuck on a skeleton that `toggleEntry` then refuses to
        // retry. Every result is keyed, so a late response is written to its own entry and a
        // superseded one is harmless.
        loadFullContent: async ({ key }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.loadFullContentFailure(key)
                return
            }
            try {
                // `key` is an exact match on the unique (team, key) pair. `text` would be an ILIKE
                // across key *and* content, which can bury the row we asked for under newer
                // entries that merely mention it.
                const results = await signalsScoutScratchpadSearch(String(teamId), { key })
                const match = results.find((entry) => entry.key === key)
                if (match) {
                    actions.loadFullContentSuccess(key, match.content ?? '')
                    return
                }
                actions.loadFullContentFailure(key)
            } catch {
                // The preview stays on screen, so a failure costs the reader the tail of one note
                // rather than the whole row.
                actions.loadFullContentFailure(key)
            }
        },

        // One request per report, so the cap above is what keeps this bounded. A missing report
        // resolves to null and is never asked for again.
        resolveReportTitles: async () => {
            // Ask the canonical project, not the environment in the URL. The harness writes every
            // scout row through `_canonical_team_id` (parent_team_id or team_id), so a report a
            // scratchpad key names belongs to the parent, while the reports endpoint filters by the
            // team the URL carries and does not canonicalize it. A child-environment id would 404
            // every title. `currentProjectId` mirrors that canonical id, and equals the team id for
            // a root project; it reads '@current' until the team loads, which we reject.
            const projectId = teamLogic.values.currentProjectId
            // An id reaches `reportTitles` only when its response lands, so a pass that starts
            // while another is in flight would list, and ask for, every id the first one is
            // already fetching. Two loads answering at different times is ordinary here.
            const inFlight: Set<string> = (cache.resolvingReportIds ??= new Set<string>())
            const ids = values.unresolvedReportIds.filter((reportId) => !inFlight.has(reportId))
            if (!projectId || projectId === '@current' || ids.length === 0) {
                return
            }
            for (const reportId of ids) {
                inFlight.add(reportId)
            }
            await Promise.all(
                ids.map(async (reportId) => {
                    try {
                        const report = await signalsReportsRetrieve(String(projectId), reportId)
                        actions.setReportTitle(reportId, report.title ?? null)
                    } catch (error) {
                        // A stored null asserts the report is gone and stops the key being asked
                        // for again, so only a 404 earns one. Anything else is transient: leave the
                        // id unresolved, so the next pass asks again rather than pinning the row to
                        // its shortened UUID for the rest of the session.
                        if (error instanceof ApiError && error.status === 404) {
                            actions.setReportTitle(reportId, null)
                        }
                    } finally {
                        inFlight.delete(reportId)
                    }
                })
            )
        },
    })),

    afterMount(({ actions }) => {
        actions.loadEntries()
    }),
])
