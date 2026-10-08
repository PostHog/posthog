import { useActions, useValues } from 'kea'

import { IconNotebook } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils/strings'

import type { ScratchpadFacet, ScratchpadTimeFilter } from '../../logics/scratchpadLogic'
import { scratchpadLogic } from '../../logics/scratchpadLogic'
import { stripScoutPrefix } from '../../utils/scoutRunsWindow'
import { BOOKKEEPING_KINDS } from '../../utils/scratchpadKeys'
import { ScratchpadLedger } from './ScratchpadLedger'

const TIME_OPTIONS: { value: ScratchpadTimeFilter; label: string }[] = [
    { value: 'window', label: 'Loaded window' },
    { value: '1h', label: 'Last hour' },
    { value: '24h', label: 'Last 24 hours' },
    { value: '7d', label: 'Last 7 days' },
    { value: '30d', label: 'Last 30 days' },
]

const HIDE_BOOKKEEPING_TOOLTIP = `Drops the notes scouts write for themselves: ${[...BOOKKEEPING_KINDS].join(', ')}.`

/**
 * Browse + filter surface for the scout fleet's scratchpad (`SignalScratchpad`). Frames what the
 * scratchpad is up top, says how much of it is loaded and over what span, then hands the rows to a
 * ledger the reader can narrow by scout, kind, topic and time.
 *
 * Read-only: the harness writes scratchpad entries on internal scope; humans inspect them here.
 */
export function ScratchpadPanel(): JSX.Element {
    const {
        entries,
        entriesLoading,
        loadFailed,
        searchResultsLoading,
        searchFailed,
        visibleEntries,
        filteredEntries,
        totalCount,
        loadedSpanLabel,
        scoutFacets,
        kindFacets,
        topicFacets,
        windowStats,
        visibleBookkeepingCount,
        hasActiveFilters,
        canLoadOlderEntries,
        olderEntriesFailed,
        olderEntriesLoading,
        searchText,
        scoutFilter,
        kindFilter,
        topicFilter,
        timeFilter,
        hideBookkeeping,
    } = useValues(scratchpadLogic)
    const {
        setSearchText,
        setScoutFilter,
        setKindFilter,
        setTopicFilter,
        setTimeFilter,
        setHideBookkeeping,
        clearFilters,
        loadEntries,
        loadSearchResults,
        loadOlderEntries,
    } = useActions(scratchpadLogic)

    const isSearching = searchText.trim().length > 0
    // The window loads once on mount; a search loads its own result set on top of it. Either
    // list shows a skeleton until its first response, and its own retry when that response fails.
    const isInitialLoad = isSearching ? visibleEntries === null && !searchFailed : entriesLoading && entries === null
    const listFailed = isSearching ? searchFailed : loadFailed
    const retry = isSearching ? loadSearchResults : loadEntries
    const retryLoading = isSearching ? searchResultsLoading : entriesLoading

    return (
        <div className="flex flex-col gap-4 px-4 py-3">
            <ScratchpadHeader
                totalCount={totalCount}
                loadedSpanLabel={loadedSpanLabel}
                scoutCount={windowStats.scouts}
                topicCount={windowStats.topics}
                expiringSoonCount={windowStats.expiringSoon}
                loading={isInitialLoad}
            />

            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search keys and notes…"
                        value={searchText}
                        onChange={setSearchText}
                        className="min-w-[12rem] flex-1"
                        allowClear
                    />
                    <FacetSelect
                        placeholder="Scout: all"
                        facets={scoutFacets}
                        value={scoutFilter}
                        onChange={setScoutFilter}
                        labelOf={stripScoutPrefix}
                    />
                    <FacetSelect
                        placeholder="Kind: any"
                        facets={kindFacets}
                        value={kindFilter}
                        onChange={setKindFilter}
                    />
                    <FacetSelect
                        placeholder="Topic: any"
                        facets={topicFacets}
                        value={topicFilter}
                        onChange={setTopicFilter}
                    />
                    <LemonSelect size="small" value={timeFilter} onChange={setTimeFilter} options={TIME_OPTIONS} />
                </div>
                <Tooltip title={HIDE_BOOKKEEPING_TOOLTIP}>
                    <LemonSwitch
                        checked={hideBookkeeping}
                        onChange={setHideBookkeeping}
                        label="Hide bookkeeping"
                        size="small"
                        className="w-fit"
                    />
                </Tooltip>
            </div>

            {isInitialLoad ? (
                <LemonSkeleton className="h-64 w-full rounded" />
            ) : listFailed && (!filteredEntries || filteredEntries.length === 0) ? (
                <ScratchpadErrorState onRetry={() => retry()} loading={retryLoading} />
            ) : !filteredEntries || filteredEntries.length === 0 ? (
                <ScratchpadEmptyState
                    hasActiveFilters={hasActiveFilters}
                    loadedSpanLabel={loadedSpanLabel}
                    onClearFilters={clearFilters}
                />
            ) : (
                <>
                    {listFailed && (
                        // A reload rejected while a previous result set is still on screen, so these
                        // rows answer the search or the span the reader had before. Say so, rather
                        // than let the ledger assert they match the controls above.
                        <LemonBanner
                            type="warning"
                            action={{ children: 'Retry', onClick: () => retry(), loading: retryLoading }}
                        >
                            Couldn't refresh the list. These rows may not match the filters above.
                        </LemonBanner>
                    )}
                    <ScratchpadLedger />
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                        <span>
                            Showing the newest {pluralize(filteredEntries.length, 'entry', 'entries')}.
                            {canLoadOlderEntries ? ' Older memory is still there.' : ''}
                        </span>
                        {canLoadOlderEntries && (
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                onClick={() => loadOlderEntries()}
                                loading={olderEntriesLoading}
                            >
                                Load older entries
                            </LemonButton>
                        )}
                        {canLoadOlderEntries && olderEntriesFailed && (
                            <span className="text-danger">Couldn't load them. Try again.</span>
                        )}
                        <span className="flex-1" />
                        {visibleBookkeepingCount > 0 && !hideBookkeeping && (
                            <span>{visibleBookkeepingCount} of these are bookkeeping</span>
                        )}
                    </div>
                </>
            )}
        </div>
    )
}

/** One multi-select over a facet of the loaded window, each option carrying how many rows match. */
function FacetSelect({
    placeholder,
    facets,
    value,
    onChange,
    labelOf,
}: {
    placeholder: string
    facets: ScratchpadFacet[]
    value: string[]
    onChange: (value: string[]) => void
    labelOf?: (value: string) => string
}): JSX.Element {
    return (
        // The select fills its parent, so the width it gets has to come from a wrapper.
        <div className="w-44">
            <LemonInputSelect
                mode="multiple"
                size="small"
                placeholder={placeholder}
                value={value}
                onChange={onChange}
                options={facets.map((facet) => ({
                    key: facet.value,
                    label: `${labelOf ? labelOf(facet.value) : facet.value} (${facet.count})`,
                }))}
            />
        </div>
    )
}

function Stat({ value, label, loading }: { value: string; label: string; loading: boolean }): JSX.Element {
    return (
        <div className="flex min-w-24 flex-col">
            {loading ? (
                <LemonSkeleton className="h-5 w-10 rounded" />
            ) : (
                <span className="text-base font-semibold tabular-nums text-default">{value}</span>
            )}
            <span className="text-xs text-muted">{label}</span>
        </div>
    )
}

function ScratchpadHeader({
    totalCount,
    loadedSpanLabel,
    scoutCount,
    topicCount,
    expiringSoonCount,
    loading,
}: {
    totalCount: number | null
    loadedSpanLabel: string | null
    scoutCount: number
    topicCount: number
    expiringSoonCount: number
    loading: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <IconNotebook className="size-5 text-primary-3000" />
                <span className="text-base font-semibold text-default">Scout scratchpad</span>
            </div>
            <p className="mb-0 text-sm text-secondary">
                What your scouts have written down while scanning this project: patterns they trust, baselines they
                settled on, things they ruled out, and the bookkeeping that keeps them from repeating themselves.
            </p>
            <div className="flex flex-wrap gap-x-6 gap-y-2">
                {/* The count is what's loaded, not what exists: the endpoint caps at 1,000 newest-first,
                    which on a busy project is a few hours. Labelling it with the span it covers is what
                    stops it reading as the whole memory. */}
                <Stat
                    value={totalCount === null ? '—' : String(totalCount)}
                    label={loadedSpanLabel ? `entries, ${loadedSpanLabel}` : 'entries loaded'}
                    loading={loading}
                />
                <Stat value={String(scoutCount)} label="scouts writing" loading={loading} />
                <Stat value={String(topicCount)} label="topics" loading={loading} />
                <Stat value={String(expiringSoonCount)} label="expiring soon" loading={loading} />
            </div>
        </div>
    )
}

function ScratchpadErrorState({ onRetry, loading }: { onRetry: () => void; loading: boolean }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 rounded border border-dashed border-primary bg-bg-light px-4 py-8 text-center text-sm text-muted">
            <span>
                Couldn't load the scratchpad. The scout API may be unavailable or this project may not be enrolled yet.
            </span>
            <LemonButton type="secondary" size="small" onClick={onRetry} loading={loading}>
                Retry
            </LemonButton>
        </div>
    )
}

function ScratchpadEmptyState({
    hasActiveFilters,
    loadedSpanLabel,
    onClearFilters,
}: {
    hasActiveFilters: boolean
    loadedSpanLabel: string | null
    onClearFilters: () => void
}): JSX.Element {
    if (!hasActiveFilters) {
        return (
            <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-8 text-center text-sm text-muted">
                Your scouts haven't written anything down yet. As they scan your project, their entries show up here.
            </div>
        )
    }
    return (
        <div className="flex flex-col items-center gap-2 rounded border border-dashed border-primary bg-bg-light px-4 py-8 text-center text-sm text-muted">
            <span>
                No entries match. Clear the filters to see everything from the {loadedSpanLabel ?? 'loaded window'}.
            </span>
            <LemonButton type="secondary" size="small" onClick={onClearFilters}>
                Clear filters
            </LemonButton>
        </div>
    )
}
