import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPlayFilled } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ObservationResultSummary } from '../components/ObservationCard'
import { ScannerOutputBadge } from '../components/ScannerOutputBadge'
import { TimestampCitation } from '../components/TimestampCitation'
import type { ObservationSearchResultApi, ReplayObservationApi } from '../generated/api.schemas'
import { observationDetailUrl } from '../observations/replayObservationLogic'
import { parseCitedSegments } from '../utils/citations'
import { hasScannerPage, scannerLabel } from '../utils/observation'
import { firstCitedTimestampMs, searchReturnParams } from './observationQueries'
import { type ObservationSearchLogicProps, SEARCH_PAGE_SIZE, observationSearchLogic } from './observationSearchLogic'
import { type Tier, groupByTier } from './resultTiers'
import { snippetSegments } from './snippetSegments'

// The global SessionPlayerModal opens from the hash and seeks from `t`.
function watchMomentUrl(
    observation: ReplayObservationApi,
    citedMs: number | null,
    { location, searchParams, hashParams }: typeof router.values
): string {
    return combineUrl(
        location.pathname,
        { ...searchParams, t: citedMs !== null ? Math.floor(citedMs / 1000) : undefined },
        { ...hashParams, sessionRecordingId: observation.session_id }
    ).url
}

function MomentCard({
    result,
    searchedQuery,
    returnParams,
}: {
    result: ObservationSearchResultApi
    searchedQuery: string
    returnParams: Record<string, string>
}): JSX.Element {
    const routerValues = useValues(router)
    const observation = result.observation
    const snapshot = observation.scanner_snapshot
    const email = observation.recording_subject_email
    const subjectClass = clsx('text-xs truncate', !email && 'font-mono')
    const citedMs = firstCitedTimestampMs(observation)
    const snippet = parseCitedSegments(result.matched_content, undefined)
    return (
        <div
            className="flex flex-col border border-primary rounded-lg bg-surface-primary overflow-hidden"
            data-attr="vision-search-result"
        >
            <Link
                to={watchMomentUrl(observation, citedMs, routerValues)}
                className="relative block aspect-video bg-surface-tertiary text-primary hover:bg-fill-highlight-100"
                data-attr="vision-search-result-watch"
            >
                {snapshot && (
                    <span className="absolute top-2 left-2">
                        <ScannerOutputBadge scannerType={snapshot.scanner_type} size="small" />
                    </span>
                )}
                <span className="absolute inset-0 flex items-center justify-center">
                    <span className="size-10 rounded-full bg-surface-primary border border-primary flex items-center justify-center text-lg">
                        <IconPlayFilled />
                    </span>
                </span>
                <span className="absolute bottom-2 right-2 text-xs font-medium px-1.5 py-0.5 rounded bg-surface-primary border border-primary">
                    {citedMs !== null
                        ? `Watch at ${colonDelimitedDuration(Math.floor(citedMs / 1000), null)}`
                        : 'Watch recording'}
                </span>
            </Link>
            <div className="flex flex-col gap-1.5 p-3 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    {hasScannerPage(observation) ? (
                        <Link
                            to={urls.replayVision(observation.scanner_id)}
                            className="font-semibold text-sm truncate text-primary"
                            data-attr="vision-search-result-scanner"
                        >
                            {scannerLabel(observation)}
                        </Link>
                    ) : (
                        <span className="font-semibold text-sm truncate">{scannerLabel(observation)}</span>
                    )}
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
                <div className="flex items-center gap-2 min-w-0 text-xs">
                    {observation.distinct_id ? (
                        <Link
                            to={urls.personByDistinctId(observation.distinct_id)}
                            className={clsx(subjectClass, 'text-primary')}
                            data-attr="vision-search-result-person"
                        >
                            {email ?? observation.distinct_id}
                        </Link>
                    ) : (
                        <span className={clsx(subjectClass, 'text-muted')}>{email ?? observation.session_id}</span>
                    )}
                    <Link
                        to={observationDetailUrl(observation.id, returnParams)}
                        className="ml-auto shrink-0"
                        data-attr="vision-search-result-detail"
                    >
                        Details
                    </Link>
                </div>
            </div>
        </div>
    )
}

function TierHeading({ tier }: { tier: Tier }): JSX.Element {
    return (
        <div className="flex items-baseline gap-2 text-xs">
            <span className="font-semibold">{tier === 'top' ? 'Top matches' : 'Other matches'}</span>
            <span className="text-muted">
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
        scannerId,
        sourceObservationId,
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
    const returnParams = searchReturnParams(searchedQuery ?? '', scannerId, sourceObservationId)
    return (
        <div className={clsx('flex flex-col gap-3', searching && 'opacity-50 pointer-events-none')}>
            <div className="text-xs text-secondary">
                {truncated ? 'Showing the top ' : ''}
                {pluralize(results.length, 'match', 'matches')}, best first
            </div>
            {groupByTier(pageResults, topMatchDistanceCutoff).map((group) => (
                <div key={group.tier ?? 'all'} className="flex flex-col gap-2">
                    {group.tier && <TierHeading tier={group.tier} />}
                    <div className="grid gap-3 grid-cols-1 @xl:grid-cols-2 @3xl:grid-cols-3">
                        {group.results.map((result) => (
                            <MomentCard
                                key={result.observation.id}
                                result={result}
                                searchedQuery={searchedQuery ?? ''}
                                returnParams={returnParams}
                            />
                        ))}
                    </div>
                </div>
            ))}
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
