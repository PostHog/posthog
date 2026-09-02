import { useActions, useValues } from 'kea'

import { IconChevronDown, IconClock, IconNotebook, IconStack } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { scratchpadLogic } from '../../logics/scratchpadLogic'
import { ScratchpadEntryCard } from './ScratchpadEntryCard'

/**
 * Browse + search surface for the scout fleet's scratchpad (`SignalScratchpad`). Frames what the
 * scratchpad is up top (the context scouts jot down + how much has accumulated), then lets the user
 * read it newest-first or clustered by topic, and search it via the endpoint's ILIKE.
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
        totalCount,
        lastUpdatedAt,
        groups,
        searchText,
        grouping,
        expandedNamespaces,
    } = useValues(scratchpadLogic)
    const { setSearchText, setGrouping, toggleNamespace, loadEntries, loadSearchResults } = useActions(scratchpadLogic)

    const isSearching = searchText.trim().length > 0
    // The window loads once on mount; a search loads its own result set on top of it. Either
    // list shows a skeleton until its first response, and its own retry when that response fails.
    const isInitialLoad = isSearching ? visibleEntries === null && !searchFailed : entriesLoading && entries === null
    const listFailed = isSearching ? searchFailed : loadFailed
    const retry = isSearching ? loadSearchResults : loadEntries
    const retryLoading = isSearching ? searchResultsLoading : entriesLoading

    return (
        <div className="flex flex-col gap-4 px-4 py-3">
            <ScratchpadHeader totalCount={totalCount} lastUpdatedAt={lastUpdatedAt} loading={isInitialLoad} />

            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search the scratchpad…"
                    value={searchText}
                    onChange={setSearchText}
                    className="flex-1 min-w-[12rem]"
                    allowClear
                />
                <LemonSegmentedButton
                    size="small"
                    value={grouping}
                    onChange={setGrouping}
                    options={[
                        { value: 'recent', label: 'Recent', icon: <IconClock /> },
                        { value: 'topic', label: 'By topic', icon: <IconStack /> },
                    ]}
                />
            </div>

            {isInitialLoad ? (
                <div className="flex flex-col gap-2">
                    <ScratchpadEntryCardSkeleton />
                    <ScratchpadEntryCardSkeleton />
                    <ScratchpadEntryCardSkeleton />
                </div>
            ) : listFailed && (!visibleEntries || visibleEntries.length === 0) ? (
                <ScratchpadErrorState onRetry={() => retry()} loading={retryLoading} />
            ) : !visibleEntries || visibleEntries.length === 0 ? (
                <ScratchpadEmptyState isSearching={isSearching} />
            ) : grouping === 'topic' ? (
                <div className="flex flex-col gap-3">
                    {groups.map((group) => {
                        // Collapsed by default for a high-level scan; a search forces every matching
                        // topic open so results stay visible without a click.
                        const isExpanded = isSearching || expandedNamespaces.includes(group.namespace)
                        return (
                            <div key={group.namespace} className="flex flex-col gap-2">
                                <button
                                    type="button"
                                    onClick={() => toggleNamespace(group.namespace)}
                                    className="flex items-center gap-2 text-left"
                                    aria-expanded={isExpanded}
                                >
                                    <IconChevronDown
                                        className={`size-4 shrink-0 text-muted transition-transform ${
                                            isExpanded ? '' : '-rotate-90'
                                        }`}
                                    />
                                    <span className="text-xs font-medium uppercase tracking-wide text-default">
                                        {group.label}
                                    </span>
                                    <span className="text-[11px] text-muted">
                                        {pluralize(group.entries.length, 'entry', 'entries')}
                                    </span>
                                </button>
                                {isExpanded &&
                                    group.entries.map((entry) => <ScratchpadEntryCard key={entry.key} entry={entry} />)}
                            </div>
                        )
                    })}
                </div>
            ) : (
                <div className="flex flex-col gap-2">
                    {visibleEntries.map((entry) => (
                        <ScratchpadEntryCard key={entry.key} entry={entry} />
                    ))}
                </div>
            )}
        </div>
    )
}

function ScratchpadEntryCardSkeleton(): JSX.Element {
    return (
        <div className="flex h-20 flex-col gap-3 rounded border border-primary bg-bg-light px-3 py-2">
            <div className="flex items-center gap-2">
                <LemonSkeleton className="size-4 shrink-0 rounded" />
                <LemonSkeleton className="h-4 w-16 rounded" />
                <LemonSkeleton className="h-3 w-40 rounded" />
                <span className="flex-1" />
                <LemonSkeleton className="h-3 w-24 rounded" />
            </div>
            <div className="flex flex-col gap-1 pl-6">
                <LemonSkeleton className="h-3 w-full rounded" />
                <LemonSkeleton className="h-3 w-2/3 rounded" />
            </div>
        </div>
    )
}

function ScratchpadHeader({
    totalCount,
    lastUpdatedAt,
    loading,
}: {
    totalCount: number | null
    lastUpdatedAt: string | null
    loading: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <IconNotebook className="size-5 text-primary-3000" />
                <span className="text-base font-semibold text-default">Scout scratchpad</span>
            </div>
            <p className="mb-0 text-sm text-secondary">
                Where your scouts jot down useful context as they scan your project — things they've classified, ruled
                out, or the vocabulary they've settled on. Browse it to see what they're picking up about your setup.
            </p>
            <div className="flex min-h-4 items-center">
                {loading ? (
                    <LemonSkeleton className="h-3 w-36 rounded" />
                ) : totalCount !== null && totalCount > 0 ? (
                    <span className="text-xs text-muted">
                        {pluralize(totalCount, 'entry', 'entries')}
                        {lastUpdatedAt ? (
                            <>
                                {' · last updated '}
                                <TZLabel time={lastUpdatedAt} />
                            </>
                        ) : null}
                    </span>
                ) : null}
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

function ScratchpadEmptyState({ isSearching }: { isSearching: boolean }): JSX.Element {
    return (
        <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-8 text-center text-sm text-muted">
            {isSearching
                ? 'No entries match your search.'
                : "Your scouts haven't written anything down yet. As they scan your project, their entries show up here."}
        </div>
    )
}
