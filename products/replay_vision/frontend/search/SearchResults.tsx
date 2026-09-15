import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { Fragment } from 'react'

import { IconPlay } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { ObservationResultSummary } from '../components/ObservationCard'
import { ScannerOutputBadge } from '../components/ScannerOutputBadge'
import { TimestampCitation } from '../components/TimestampCitation'
import type { ObservationSearchResultApi, ReplayObservationApi } from '../generated/api.schemas'
import { observationDetailUrl } from '../observations/replayObservationLogic'
import { parseCitedSegments } from '../utils/citations'
import { hasScannerPage, scannerLabel } from '../utils/observation'
import { firstCitedTimestampMs } from './observationQueries'
import { type ObservationSearchLogicProps, SEARCH_PAGE_SIZE, observationSearchLogic } from './observationSearchLogic'
import { snippetSegments } from './snippetSegments'

function countLabel(count: number, truncated: boolean): string {
    if (truncated) {
        return `Showing the top ${count === 1 ? 'match' : `${count} matches`}, best first`
    }
    return `${count === 1 ? '1 match' : `${count} matches`}, best first`
}

// The global SessionPlayerModal opens from the hash and seeks from `t`, so the recording plays over the results.
function watchMomentUrl(
    observation: ReplayObservationApi,
    citedMs: number | null,
    { location, searchParams, hashParams }: typeof router.values
): string {
    return combineUrl(
        location.pathname,
        { ...searchParams, t: citedMs ? Math.floor(citedMs / 1000) : undefined },
        { ...hashParams, sessionRecordingId: observation.session_id }
    ).url
}

function SubjectLabel({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    const email = observation.recording_subject_email
    const className = clsx('text-xs truncate', !email && 'font-mono')
    if (!observation.distinct_id) {
        return <span className={clsx(className, 'text-muted')}>{email ?? observation.session_id}</span>
    }
    return (
        <Link
            to={urls.personByDistinctId(observation.distinct_id)}
            className={className}
            data-attr="vision-search-result-person"
        >
            {email ?? observation.distinct_id}
        </Link>
    )
}

function SearchResultRow({
    result,
    searchedQuery,
}: {
    result: ObservationSearchResultApi
    searchedQuery: string
}): JSX.Element {
    const routerValues = useValues(router)
    const observation = result.observation
    const snapshot = observation.scanner_snapshot
    const citedMs = firstCitedTimestampMs(observation)
    const snippet = parseCitedSegments(result.matched_content, undefined)
    return (
        <div
            className="px-3 py-3 space-y-2 text-primary border-b border-secondary last:border-b-0 hover:bg-fill-highlight-100"
            data-attr="vision-search-result"
        >
            <div className="flex items-center gap-2 min-w-0">
                {hasScannerPage(observation) ? (
                    <Link
                        to={urls.replayVision(observation.scanner_id)}
                        className="font-semibold text-sm truncate"
                        data-attr="vision-search-result-scanner"
                    >
                        {scannerLabel(observation)}
                    </Link>
                ) : (
                    <span className="font-semibold text-sm truncate">{scannerLabel(observation)}</span>
                )}
                {snapshot && <ScannerOutputBadge scannerType={snapshot.scanner_type} size="small" />}
                <SubjectLabel observation={observation} />
                <span className="ml-auto shrink-0 text-xs text-muted">
                    <TZLabel time={observation.created_at} />
                </span>
            </div>
            {snippet.length > 0 && (
                <div className="text-sm text-secondary line-clamp-2">
                    {snippet.map((cited, citedIndex) =>
                        cited.kind === 'chip' ? (
                            <TimestampCitation key={citedIndex} timestampMs={cited.timestamp_ms} />
                        ) : (
                            snippetSegments(cited.value, searchedQuery).map((segment, index) => (
                                <span
                                    key={`${citedIndex}-${index}`}
                                    className={segment.highlighted ? 'font-semibold' : undefined}
                                >
                                    {segment.text}
                                </span>
                            ))
                        )
                    )}
                </div>
            )}
            <ObservationResultSummary observation={observation} />
            <div className="flex items-center gap-3 text-xs">
                <Link
                    to={observationDetailUrl(observation.id, {})}
                    className="inline-flex items-center gap-1"
                    data-attr="vision-search-result-detail"
                >
                    View details
                </Link>
                <Link
                    to={watchMomentUrl(observation, citedMs, routerValues)}
                    className="inline-flex items-center gap-1"
                    data-attr="vision-search-result-watch"
                >
                    <IconPlay className="size-3" />
                    {citedMs !== null
                        ? `Watch at ${colonDelimitedDuration(Math.floor(citedMs / 1000), null)}`
                        : 'Watch recording'}
                </Link>
            </div>
        </div>
    )
}

type Tier = 'top' | 'other'

function TierHeading({ tier }: { tier: Tier }): JSX.Element {
    return (
        <div className="flex items-baseline gap-2 px-3 py-2 border-b border-secondary bg-surface-secondary">
            <span className="font-semibold text-xs">{tier === 'top' ? 'Top matches' : 'Other matches'}</span>
            <span className="text-muted text-xs">
                {tier === 'top' ? 'Closest to what you described.' : 'Related, but further from what you described.'}
            </span>
        </div>
    )
}

export function SearchResults(logicProps: ObservationSearchLogicProps): JSX.Element | null {
    const logic = observationSearchLogic(logicProps)
    const {
        results,
        searching,
        searchedQuery,
        truncated,
        topMatchDistanceCutoff,
        page,
        pageCount,
        pageResults,
        pageStartIndex,
        pageEndIndex,
    } = useValues(logic)
    const { setPage } = useActions(logic)

    if (!results || results.length === 0) {
        return null
    }
    const tierOf = (result: ObservationSearchResultApi): Tier | null =>
        topMatchDistanceCutoff === null ? null : result.distance <= topMatchDistanceCutoff ? 'top' : 'other'
    return (
        <div className={clsx('flex flex-col gap-3', searching && 'opacity-50 pointer-events-none')}>
            <div className="text-xs text-secondary">{countLabel(results.length, truncated)}</div>
            <div className="flex flex-col border border-secondary rounded overflow-hidden bg-surface-primary">
                {pageResults.map((result, index) => {
                    const tier = tierOf(result)
                    const startsTier = tier !== null && (index === 0 || tierOf(pageResults[index - 1]) !== tier)
                    return (
                        <Fragment key={result.observation.id}>
                            {startsTier && <TierHeading tier={tier} />}
                            <SearchResultRow result={result} searchedQuery={searchedQuery ?? ''} />
                        </Fragment>
                    )
                })}
            </div>
            <PaginationControl
                pagination={{ controlled: true, pageSize: SEARCH_PAGE_SIZE }}
                currentPage={page}
                setCurrentPage={setPage}
                pageCount={pageCount}
                dataSourcePage={pageResults}
                entryCount={results.length}
                currentStartIndex={pageStartIndex}
                currentEndIndex={pageEndIndex}
                nouns={['match', 'matches']}
            />
        </div>
    )
}
