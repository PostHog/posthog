import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useState } from 'react'

import { IconPlusSmall, IconSearch, IconX } from '@posthog/icons'
import { LemonButton, Popover, Spinner } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { visionScannersListLogic } from '../logics/visionScannersListLogic'
import type { ReplayScanner } from '../replay_scanners/types'
import { type ObservationSearchLogicProps, observationSearchLogic } from './observationSearchLogic'
import { ScannerScopeSelect } from './ScannerScopeSelect'
import { SearchResults } from './SearchResults'

const FALLBACK_EXAMPLE_QUERIES = ['users who got stuck and gave up', 'rage clicking out of frustration']

// Phrased the way this scanner type writes, so the examples match semantically.
function exampleQueries(scanner: ReplayScanner | null): string[] {
    switch (scanner?.scanner_type) {
        case 'monitor':
            return ['the most severe cases', 'sessions where the user recovered']
        case 'classifier': {
            const categories = scanner.scanner_config.tags.filter((tag) => tag.trim())
            return categories.length > 0 ? categories.slice(0, 3) : FALLBACK_EXAMPLE_QUERIES
        }
        case 'scorer':
            return ['sessions that struggled the most', 'sessions that went smoothly']
        case 'summarizer':
            return ['users who completed what they came to do', 'confusion and backtracking']
        default:
            return FALLBACK_EXAMPLE_QUERIES
    }
}

function SuggestedSearches({
    queries,
    loading,
    onPick,
}: {
    queries: string[]
    loading: boolean
    onPick: (query: string) => void
}): JSX.Element {
    return (
        <div className="rounded bg-surface-secondary px-3 py-2 flex flex-col gap-2 min-w-0 min-h-16">
            <span className="text-xs text-secondary">Suggested searches</span>
            {loading ? (
                <Spinner className="self-center" />
            ) : queries.length === 0 ? (
                <span className="text-xs text-tertiary">Themes from what your scanners observed will appear here.</span>
            ) : (
                <div className="flex flex-wrap gap-1">
                    {queries.map((query) => (
                        <LemonButton
                            key={query}
                            type="secondary"
                            size="xsmall"
                            className="max-w-full"
                            onClick={() => onPick(query)}
                            data-attr="vision-search-example"
                        >
                            <span className="truncate">{query}</span>
                        </LemonButton>
                    ))}
                </div>
            )}
        </div>
    )
}

export function ObservationSearch({ className }: { className?: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { scanners } = useValues(visionScannersListLogic)
    const logicProps: ObservationSearchLogicProps = { teamId: currentTeamId, userId: user?.uuid ?? null }
    const logic = observationSearchLogic(logicProps)
    const {
        query,
        scannerId,
        results,
        searching,
        searchedQuery,
        sourceObservationId,
        recentQueries,
        suggestedQueries,
        suggestedQueriesLoading,
    } = useValues(logic)
    const { setQuery, setScannerId, search, clearSearch } = useActions(logic)

    const [recentsOpen, setRecentsOpen] = useState(false)
    const [highlighted, setHighlighted] = useState<number | null>(null)

    const selectedScanner = (scanners.find((scanner) => scanner.id === scannerId) as ReplayScanner | undefined) ?? null
    const suggestions = suggestedQueries.length > 0 ? suggestedQueries : exampleQueries(selectedScanner)
    const typed = query.trim().toLowerCase()
    const matchingRecents = recentQueries.filter((recent) => recent !== query && recent.toLowerCase().includes(typed))
    const showRecents = recentsOpen && dataProcessingAccepted && matchingRecents.length > 0
    const runQuery = (value: string): void => {
        setRecentsOpen(false)
        setHighlighted(null)
        setQuery(value)
        search()
    }
    const idle = results === null && !searching
    const canSubmit = dataProcessingAccepted && !searching && !!query.trim()
    const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
        if (event.nativeEvent.isComposing) {
            return
        }
        if (showRecents && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
            event.preventDefault()
            const step = event.key === 'ArrowDown' ? 1 : -1
            setHighlighted(((highlighted ?? -1) + step + matchingRecents.length) % matchingRecents.length)
        } else if (event.key === 'Escape') {
            setRecentsOpen(false)
            setHighlighted(null)
        } else if (event.key === 'Enter') {
            if (showRecents && highlighted !== null) {
                runQuery(matchingRecents[highlighted])
            } else if (canSubmit) {
                setRecentsOpen(false)
                search()
            }
        }
    }

    return (
        <div
            className={clsx(
                '@container border border-primary rounded-lg bg-surface-primary p-4 flex flex-col gap-3',
                className
            )}
            data-attr="vision-search"
        >
            {/* The grid keeps the input width steady when the suggestions column leaves. */}
            <div className="grid gap-4 @3xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <div className="flex flex-col gap-2">
                    <Popover
                        visible={showRecents}
                        onClickOutside={() => setRecentsOpen(false)}
                        placement="bottom-start"
                        matchWidth
                        padded={false}
                        overlay={
                            <ul className="py-1" data-attr="vision-search-recent-list">
                                {matchingRecents.map((recent, index) => (
                                    <li key={recent}>
                                        {/* Mouse down would blur the input and close the list first. */}
                                        <button
                                            type="button"
                                            className={clsx(
                                                'w-full text-left px-3 py-1.5 text-sm truncate hover:bg-fill-button-tertiary-hover',
                                                index === highlighted && 'bg-fill-button-tertiary-hover'
                                            )}
                                            onMouseDown={(event) => event.preventDefault()}
                                            onClick={() => runQuery(recent)}
                                            data-attr="vision-search-recent"
                                        >
                                            {recent}
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        }
                    >
                        <div className="input-like border-secondary flex items-center gap-2 relative w-full bg-fill-input rounded-lg py-1 pl-1 pr-1">
                            <ScannerScopeSelect scanners={scanners} value={scannerId} onChange={setScannerId} />
                            <input
                                type="text"
                                value={query}
                                onChange={(event) => {
                                    setQuery(event.target.value)
                                    setRecentsOpen(true)
                                    setHighlighted(null)
                                }}
                                onFocus={() => setRecentsOpen(true)}
                                onBlur={() => setRecentsOpen(false)}
                                onKeyDown={onKeyDown}
                                placeholder="Describe what to look for"
                                aria-label="Search observations"
                                disabled={!dataProcessingAccepted}
                                autoComplete="off"
                                autoFocus
                                className="w-full py-1 text-sm bg-transparent border-none focus:outline-none"
                                data-attr="vision-search-query"
                            />
                            {query && (
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconX />}
                                    onClick={clearSearch}
                                    tooltip="Clear"
                                    data-attr="vision-search-clear"
                                />
                            )}
                            <LemonButton
                                type="primary"
                                size="small"
                                icon={<IconSearch />}
                                onClick={search}
                                loading={searching}
                                disabledReason={
                                    !dataProcessingAccepted
                                        ? 'AI data processing is turned off for your organization'
                                        : !query.trim()
                                          ? 'Describe what to look for first'
                                          : undefined
                                }
                                tooltip="Search"
                                data-attr="vision-search-submit"
                            />
                        </div>
                    </Popover>
                    {idle && (
                        <div className="text-xs text-secondary">
                            Describe a behavior in plain words. Results are ranked by how well they match.
                        </div>
                    )}
                </div>
                {idle && (
                    <SuggestedSearches queries={suggestions} loading={suggestedQueriesLoading} onPick={runQuery} />
                )}
            </div>
            {results === null && searching && (
                <div className="flex items-center gap-2 text-sm text-secondary">
                    <Spinner /> Searching…
                </div>
            )}
            {results?.length === 0 && (
                <div className="rounded bg-surface-secondary px-3 py-3 flex flex-col gap-3">
                    <div className="text-sm text-secondary">
                        {scannerId
                            ? `No matches in ${selectedScanner?.name ?? 'this scanner'} for "${searchedQuery}".`
                            : `No matches for "${searchedQuery}". Only sessions a scanner has analyzed are searchable, so nothing found can also mean no scanner is watching for this yet.`}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {scannerId ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconSearch />}
                                onClick={() => setScannerId(null)}
                                data-attr="vision-search-all-scanners"
                            >
                                Search all scanners
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlusSmall />}
                                to={
                                    combineUrl(
                                        urls.replayVisionTemplates(),
                                        searchedQuery && !sourceObservationId ? { goal: searchedQuery } : {}
                                    ).url
                                }
                                data-attr="vision-search-create-scanner"
                            >
                                Create a scanner for this
                            </LemonButton>
                        )}
                        <span className="text-xs text-secondary">or try</span>
                        {suggestions
                            .filter((suggestion) => suggestion !== searchedQuery)
                            .map((suggestion) => (
                                <LemonButton
                                    key={suggestion}
                                    type="tertiary"
                                    size="xsmall"
                                    onClick={() => runQuery(suggestion)}
                                    data-attr="vision-search-example"
                                >
                                    {suggestion}
                                </LemonButton>
                            ))}
                    </div>
                </div>
            )}
            <SearchResults {...logicProps} />
        </div>
    )
}
