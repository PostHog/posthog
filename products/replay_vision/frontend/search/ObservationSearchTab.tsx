import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ObservationResultSummary } from '../components/ObservationCard'
import { ScannerTypeBadge } from '../components/ScannerTypeBadge'
import type { ObservationSearchResultApi } from '../generated/api.schemas'
import type { ReplayScanner } from '../replay_scanners/types'
import { scannerLabel } from '../utils/observation'
import { observationSearchLogic } from './observationSearchLogic'
import { snippetSegments } from './snippetSegments'

const CROSS_SCANNER_EXAMPLE_QUERIES = ['users who got stuck and gave up', 'rage clicking out of frustration']

// Examples should read like phrases the scanner type writes into observation content, which search matches semantically
function exampleQueries(scanner: ReplayScanner | null): string[] {
    switch (scanner?.scanner_type) {
        case 'monitor':
            return ['the most severe cases', 'sessions where the user recovered']
        case 'classifier': {
            const categories = scanner.scanner_config.tags.filter((tag) => tag.trim())
            return categories.length > 0 ? categories.slice(0, 3) : CROSS_SCANNER_EXAMPLE_QUERIES
        }
        case 'scorer':
            return ['sessions that struggled the most', 'sessions that went smoothly']
        case 'summarizer':
            return ['users who completed what they came to do', 'confusion and backtracking']
        default:
            return CROSS_SCANNER_EXAMPLE_QUERIES
    }
}

function suggestionDescription(crossScanner: boolean, fromObservations: boolean): string {
    const subject = crossScanner ? 'your scanners' : 'this scanner'
    if (fromObservations) {
        return `Themes from what ${subject} observed recently.`
    }
    return `Examples to get started. Themes from what ${subject} observed will appear here once more sessions are analyzed.`
}

function QuerySection({
    title,
    description,
    queries,
    dataAttr,
    onPick,
}: {
    title: string
    description: string
    queries: string[]
    dataAttr: string
    onPick: (query: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2">
            <div>
                <div className="font-semibold">{title}</div>
                <div className="text-muted text-xs">{description}</div>
            </div>
            <div className="flex items-center justify-center gap-2 flex-wrap">
                {queries.map((query) => (
                    <LemonButton
                        key={query}
                        type="secondary"
                        size="small"
                        onClick={() => onPick(query)}
                        data-attr={dataAttr}
                    >
                        {query}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}

function countLabel(count: number, truncated: boolean): string {
    if (truncated) {
        return `Showing the top ${count === 1 ? 'match' : `${count} matches`}, best first`
    }
    return `${count === 1 ? '1 match' : `${count} matches`}, best first`
}

function SearchResultCard({
    result,
    searchedQuery,
    showScanner,
    strongMatch,
}: {
    result: ObservationSearchResultApi
    searchedQuery: string
    showScanner: boolean
    strongMatch: boolean
}): JSX.Element {
    const observation = result.observation
    const snapshot = observation.scanner_snapshot
    return (
        <Link
            to={urls.replayVisionObservation(observation.id)}
            className="block border rounded p-3 bg-surface-primary hover:border-accent space-y-2 text-primary"
            data-attr="vision-search-result"
        >
            <div className="flex items-center gap-2 min-w-0">
                {showScanner && (
                    <>
                        <span className="font-semibold text-sm truncate">{scannerLabel(observation)}</span>
                        {snapshot && (
                            <ScannerTypeBadge scannerType={snapshot.scanner_type} size="small" variant="muted" />
                        )}
                    </>
                )}
                <span className="font-mono text-xs text-muted truncate">{observation.session_id}</span>
                <span className="ml-auto shrink-0 flex items-center gap-2 text-xs text-muted">
                    {strongMatch && (
                        <LemonTag type="success" size="small">
                            Strong match
                        </LemonTag>
                    )}
                    <TZLabel time={observation.created_at} />
                </span>
            </div>
            {result.matched_content && (
                <div className="text-sm text-secondary line-clamp-2">
                    {snippetSegments(result.matched_content, searchedQuery).map((segment, index) =>
                        segment.highlighted ? (
                            <span key={index} className="font-semibold text-accent">
                                {segment.text}
                            </span>
                        ) : (
                            <Fragment key={index}>{segment.text}</Fragment>
                        )
                    )}
                </div>
            )}
            <ObservationResultSummary observation={observation} />
        </Link>
    )
}

export function ObservationSearchTab({ scanner }: { scanner: ReplayScanner | null }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const logic = observationSearchLogic({
        scannerId: scanner?.id ?? null,
        teamId: currentTeamId,
        userId: user?.uuid ?? null,
    })
    const {
        query,
        results,
        searching,
        searchedQuery,
        strongMatchDistanceCutoff,
        truncated,
        recentQueries,
        suggestedQueries,
        suggestedQueriesLoading,
    } = useValues(logic)
    const { setQuery, search } = useActions(logic)
    const crossScanner = scanner === null
    const tryQueries = suggestedQueries.length > 0 ? suggestedQueries : exampleQueries(scanner)
    const runQuery = (value: string): void => {
        setQuery(value)
        search()
    }

    return (
        <div className="w-full max-w-3xl mx-auto flex flex-col gap-4 pt-2">
            <div className="flex gap-2">
                <LemonInput
                    type="search"
                    fullWidth
                    prefix={<IconSearch />}
                    placeholder="Describe what to look for"
                    value={query}
                    onChange={setQuery}
                    onPressEnter={() => !searching && dataProcessingAccepted && search()}
                    autoFocus
                    data-attr="vision-search-query"
                />
                <LemonButton
                    type="primary"
                    onClick={() => search()}
                    loading={searching}
                    disabledReason={
                        !dataProcessingAccepted
                            ? 'AI data processing is turned off for your organization'
                            : !query.trim()
                              ? 'Describe what to look for first'
                              : undefined
                    }
                    data-attr="vision-search-submit"
                >
                    Search
                </LemonButton>
            </div>

            {results === null ? (
                searching ? (
                    <div className="flex items-center justify-center h-40">
                        <Spinner className="text-2xl" />
                    </div>
                ) : (
                    <div className="text-center pt-8 flex flex-col gap-6">
                        <div className="text-muted">
                            {crossScanner
                                ? 'Search everything your scanners have observed, ranked by how well it matches.'
                                : 'Search everything this scanner has observed, ranked by how well it matches.'}
                        </div>
                        {recentQueries.length > 0 && (
                            <QuerySection
                                title="Recent searches"
                                description="Searches that returned results, saved in this browser."
                                queries={recentQueries}
                                dataAttr="vision-search-recent"
                                onPick={runQuery}
                            />
                        )}
                        {suggestedQueriesLoading ? (
                            // Hold the section rather than flash the fixed examples and swap them out a moment later.
                            <div className="flex items-center justify-center h-16">
                                <Spinner />
                            </div>
                        ) : (
                            <QuerySection
                                title="Suggested searches"
                                description={suggestionDescription(crossScanner, suggestedQueries.length > 0)}
                                queries={tryQueries}
                                dataAttr="vision-search-example"
                                onPick={runQuery}
                            />
                        )}
                    </div>
                )
            ) : (
                <div className={clsx('flex flex-col gap-4', searching && 'opacity-50 pointer-events-none')}>
                    {results.length === 0 ? (
                        <div className="text-center text-muted pt-8">
                            No matches for "{searchedQuery}". Only sessions a scanner has analyzed are searchable.
                        </div>
                    ) : (
                        <>
                            <div className="text-muted text-sm">{countLabel(results.length, truncated)}</div>
                            <div className="flex flex-col gap-2">
                                {results.map((result) => (
                                    <SearchResultCard
                                        key={result.observation.id}
                                        result={result}
                                        searchedQuery={searchedQuery ?? ''}
                                        showScanner={crossScanner}
                                        strongMatch={
                                            strongMatchDistanceCutoff !== null &&
                                            result.distance <= strongMatchDistanceCutoff
                                        }
                                    />
                                ))}
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    )
}
