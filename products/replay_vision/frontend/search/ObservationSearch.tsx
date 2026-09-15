import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPlusSmall, IconSearch, IconX } from '@posthog/icons'
import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { ReplayScanner } from '../replay_scanners/types'
import { searchTabUrl } from './observationQueries'
import { type ObservationSearchLogicProps, observationSearchLogic } from './observationSearchLogic'
import { SearchResults } from './SearchResults'

const FALLBACK_EXAMPLE_QUERIES = ['users who got stuck and gave up', 'rage clicking out of frustration']

// Phrases this scanner type writes into observations, which search then matches semantically.
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

function QueryGroup({
    title,
    queries,
    emptyText,
    dataAttr,
    onPick,
}: {
    title: string
    queries: string[]
    emptyText: string
    dataAttr: string
    onPick: (query: string) => void
}): JSX.Element {
    return (
        <div className="rounded bg-surface-secondary px-3 py-2 flex flex-col gap-2 min-w-0">
            <span className="text-xs text-secondary">{title}</span>
            {queries.length === 0 ? (
                <span className="text-xs text-tertiary">{emptyText}</span>
            ) : (
                <div className="flex flex-wrap gap-1">
                    {queries.map((query) => (
                        <LemonButton
                            key={query}
                            type="secondary"
                            size="xsmall"
                            className="max-w-full"
                            onClick={() => onPick(query)}
                            data-attr={dataAttr}
                        >
                            <span className="truncate">{query}</span>
                        </LemonButton>
                    ))}
                </div>
            )}
        </div>
    )
}

/**
 * Semantic search over observations as a card. A null `scannerId` is the hub's cross-scanner search; a scanner
 * id scopes it to that scanner's observations, where it sits above the observations table.
 */
export function ObservationSearch({
    scannerId,
    scanner,
    className,
}: {
    scannerId: string | null
    scanner: ReplayScanner | null
    className?: string
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const logicProps: ObservationSearchLogicProps = { scannerId, teamId: currentTeamId, userId: user?.uuid ?? null }
    const logic = observationSearchLogic(logicProps)
    const { query, results, searching, searchedQuery, recentQueries, suggestedQueries, suggestedQueriesLoading } =
        useValues(logic)
    const { setQuery, search, clearSearch } = useActions(logic)

    const crossScanner = scannerId === null
    const attr = crossScanner ? 'vision-search' : 'vision-observations-search'
    const suggestions = (suggestedQueries.length > 0 ? suggestedQueries : exampleQueries(scanner)).filter(
        (suggestion) => !recentQueries.includes(suggestion)
    )
    const runQuery = (value: string): void => {
        setQuery(value)
        search()
    }
    const idle = results === null && !searching
    const inputId = `${attr}-${scannerId ?? 'all'}`
    const canSubmit = dataProcessingAccepted && !searching && !!query.trim()

    return (
        <div
            className={clsx(
                '@container border border-primary rounded-lg bg-surface-primary p-4 flex flex-col gap-3',
                className
            )}
            data-attr={attr}
        >
            {/* The prompt keeps its column in every state, so the box does not jump as the card changes. */}
            <div className="grid gap-4 @3xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
                <div className="flex flex-col gap-2">
                    <label
                        htmlFor={inputId}
                        className="input-like border-secondary flex items-center gap-2 relative w-full bg-fill-input rounded-lg py-1 pl-3 pr-1"
                    >
                        <input
                            id={inputId}
                            type="text"
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter' && !event.nativeEvent.isComposing && canSubmit) {
                                    search()
                                }
                            }}
                            placeholder="Describe what to look for"
                            aria-label="Search observations"
                            disabled={!dataProcessingAccepted}
                            autoComplete="off"
                            autoFocus={crossScanner}
                            className="w-full py-1 text-sm bg-transparent border-none focus:outline-none"
                            data-attr={`${attr}-query`}
                        />
                        {query && (
                            <LemonButton
                                size="xsmall"
                                icon={<IconX />}
                                onClick={clearSearch}
                                tooltip="Clear"
                                data-attr={`${attr}-clear`}
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
                            data-attr={`${attr}-submit`}
                        />
                    </label>
                    {idle && (
                        <div className="text-xs text-secondary">
                            Describe a behavior in plain words. Results are ranked by how well they match.
                        </div>
                    )}
                </div>
                {idle && (
                    <>
                        <QueryGroup
                            title="Recent searches"
                            queries={recentQueries}
                            emptyText="Searches that find something show up here."
                            dataAttr={`${attr}-recent`}
                            onPick={runQuery}
                        />
                        {suggestedQueriesLoading ? (
                            // Holding the strip beats flashing the fixed examples and swapping them out.
                            <div className="rounded bg-surface-secondary px-3 py-2 flex items-center justify-center min-h-16">
                                <Spinner />
                            </div>
                        ) : (
                            <QueryGroup
                                title="Suggested searches"
                                queries={suggestions}
                                emptyText="Themes from what your scanners observed will appear here."
                                dataAttr={`${attr}-example`}
                                onPick={runQuery}
                            />
                        )}
                    </>
                )}
            </div>
            {results === null && searching && (
                <div className="flex items-center gap-2 text-sm text-secondary">
                    <Spinner /> Searching…
                </div>
            )}
            {results?.length === 0 &&
                (crossScanner ? (
                    <div className="rounded bg-surface-secondary px-3 py-3 flex flex-col gap-3">
                        <div className="text-sm text-secondary">
                            No matches for "{searchedQuery}". Only sessions a scanner has analyzed are searchable, so
                            nothing found can also mean no scanner is watching for this yet.
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlusSmall />}
                                to={
                                    combineUrl(
                                        urls.replayVisionTemplates(),
                                        searchedQuery ? { goal: searchedQuery } : {}
                                    ).url
                                }
                                data-attr="vision-search-create-scanner"
                            >
                                Create a scanner for this
                            </LemonButton>
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
                ) : (
                    <div className="rounded bg-surface-secondary px-3 py-2 text-sm text-secondary">
                        No matches in this scanner for "{searchedQuery}".{' '}
                        <Link to={searchTabUrl({ q: searchedQuery ?? '' })} data-attr="vision-observations-search-all">
                            Search all scanners
                        </Link>
                    </div>
                ))}
            <SearchResults {...logicProps} crossScanner={crossScanner} />
        </div>
    )
}
