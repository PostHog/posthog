import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconGridMasonry, IconList, IconPlayFilled } from '@posthog/icons'
import { LemonCard, LemonSegmentedButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ObservationResultSummary } from '../components/ObservationCard'
import { ObservationThumbnail } from '../components/ObservationThumbnail'
import { ScannerOutputBadge } from '../components/ScannerOutputBadge'
import { TimestampCitation } from '../components/TimestampCitation'
import type { ObservationSearchResultApi, ReplayObservationApi } from '../generated/api.schemas'
import { observationDetailUrl } from '../observations/replayObservationLogic'
import { parseCitedSegments } from '../utils/citations'
import { hasScannerPage, scannerLabel } from '../utils/observation'
import { firstCitedTimestampMs, searchReturnParams } from './observationQueries'
import {
    type ObservationSearchLogicProps,
    type ResultsView,
    SEARCH_PAGE_SIZE,
    observationSearchLogic,
} from './observationSearchLogic'
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

type Tier = 'top' | 'other'
type TierGroup = { tier: Tier | null; results: ObservationSearchResultApi[] }

interface ResultProps {
    result: ObservationSearchResultApi
    searchedQuery: string
    returnParams: Record<string, string>
}

function WatchLink({ observation, compact }: { observation: ReplayObservationApi; compact?: boolean }): JSX.Element {
    const routerValues = useValues(router)
    const citedMs = firstCitedTimestampMs(observation)
    return (
        <Link
            to={watchMomentUrl(observation, citedMs, routerValues)}
            className={clsx('relative block text-primary group', compact && 'w-28')}
            data-attr="vision-search-result-watch"
        >
            {/* The card clips its own corners and draws its own edge, so the poster goes edge to edge there. */}
            <ObservationThumbnail observation={observation} className={clsx(!compact && 'rounded-none border-0')}>
                {/* A fixed dark scrim, not a theme surface: the chip sits on a frame of any colour, white included. */}
                <span
                    className={clsx(
                        'rounded-full bg-black/60 text-white flex items-center justify-center group-hover:bg-black/80',
                        compact ? 'size-6 text-sm' : 'size-10 text-lg'
                    )}
                >
                    <IconPlayFilled />
                </span>
            </ObservationThumbnail>
            {!compact && (
                <span className="absolute bottom-2 right-2 text-xs font-medium px-1.5 py-0.5 rounded bg-surface-primary border border-primary">
                    {citedMs !== null
                        ? `Watch at ${colonDelimitedDuration(Math.floor(citedMs / 1000), null)}`
                        : 'Watch recording'}
                </span>
            )}
        </Link>
    )
}

function ScannerName({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    return hasScannerPage(observation) ? (
        <Link
            to={urls.replayVision(observation.scanner_id)}
            className="font-semibold text-sm truncate text-primary"
            data-attr="vision-search-result-scanner"
        >
            {scannerLabel(observation)}
        </Link>
    ) : (
        <span className="font-semibold text-sm truncate">{scannerLabel(observation)}</span>
    )
}

function MatchSnippet({
    result,
    searchedQuery,
}: {
    result: ObservationSearchResultApi
    searchedQuery: string
}): JSX.Element | null {
    const snippet = parseCitedSegments(result.matched_content, undefined)
    if (snippet.length === 0) {
        return null
    }
    return (
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
    )
}

function SubjectLink({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    const email = observation.recording_subject_email
    const subjectClass = clsx('text-xs truncate', !email && 'font-mono')
    return observation.distinct_id ? (
        <Link
            to={urls.personByDistinctId(observation.distinct_id)}
            className={clsx(subjectClass, 'text-primary')}
            data-attr="vision-search-result-person"
        >
            {email ?? observation.distinct_id}
        </Link>
    ) : (
        <span className={clsx(subjectClass, 'text-muted')}>{email ?? observation.session_id}</span>
    )
}

function TopMatchTag(): JSX.Element {
    return (
        <LemonTag type="success" size="small">
            Top match
        </LemonTag>
    )
}

function MomentCard({ result, searchedQuery, returnParams, tier }: ResultProps & { tier: Tier | null }): JSX.Element {
    const observation = result.observation
    const snapshot = observation.scanner_snapshot
    return (
        <LemonCard className="flex flex-col rounded-lg p-0 overflow-hidden" data-attr="vision-search-result">
            <div className="relative">
                <WatchLink observation={observation} />
                <span className="absolute top-2 left-2 flex items-center gap-1">
                    {snapshot && <ScannerOutputBadge scannerType={snapshot.scanner_type} size="small" />}
                    {tier === 'top' && <TopMatchTag />}
                </span>
            </div>
            <div className="flex flex-col gap-1.5 p-3 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    <ScannerName observation={observation} />
                    <span className="ml-auto shrink-0 text-xs text-muted">
                        <TZLabel time={observation.created_at} />
                    </span>
                </div>
                <MatchSnippet result={result} searchedQuery={searchedQuery} />
                <ObservationResultSummary observation={observation} />
                <div className="flex items-center gap-2 min-w-0 text-xs">
                    <SubjectLink observation={observation} />
                    <Link
                        to={observationDetailUrl(observation.id, returnParams)}
                        className="ml-auto shrink-0"
                        data-attr="vision-search-result-detail"
                    >
                        Details
                    </Link>
                </div>
            </div>
        </LemonCard>
    )
}

function MomentRow({ result, searchedQuery, returnParams }: ResultProps): JSX.Element {
    const observation = result.observation
    const snapshot = observation.scanner_snapshot
    return (
        <LemonCard className="flex gap-3 rounded-lg p-2 min-w-0" data-attr="vision-search-result">
            <div className="shrink-0 self-center">
                <WatchLink observation={observation} compact />
            </div>
            <div className="flex flex-col gap-1 min-w-0 flex-1">
                <div className="flex items-center gap-2 min-w-0">
                    <ScannerName observation={observation} />
                    {snapshot && <ScannerOutputBadge scannerType={snapshot.scanner_type} size="small" />}
                    <SubjectLink observation={observation} />
                    <span className="ml-auto shrink-0 flex items-center gap-2 text-xs text-muted">
                        <TZLabel time={observation.created_at} />
                        <Link
                            to={observationDetailUrl(observation.id, returnParams)}
                            data-attr="vision-search-result-detail"
                        >
                            Details
                        </Link>
                    </span>
                </div>
                <MatchSnippet result={result} searchedQuery={searchedQuery} />
                <ObservationResultSummary observation={observation} />
            </div>
        </LemonCard>
    )
}

function TierHeading({ tier }: { tier: Tier }): JSX.Element {
    return (
        <div className="flex items-baseline gap-2 px-3 py-1.5 rounded border border-primary bg-surface-tertiary dark:bg-surface-secondary text-xs">
            <span className="font-semibold">{tier === 'top' ? 'Top matches' : 'Other matches'}</span>
            <span className="text-muted">
                {tier === 'top' ? 'Closest to what you described.' : 'Related, but further from what you described.'}
            </span>
        </div>
    )
}

function tierGroups(
    results: ObservationSearchResultApi[],
    tierOf: (result: ObservationSearchResultApi) => Tier | null
): TierGroup[] {
    const groups: TierGroup[] = []
    for (const result of results) {
        const tier = tierOf(result)
        const last = groups[groups.length - 1]
        if (last && last.tier === tier) {
            last.results.push(result)
        } else {
            groups.push({ tier, results: [result] })
        }
    }
    return groups
}

function ResultsSkeleton({ view }: { view: ResultsView }): JSX.Element {
    const lines = (
        <div className="flex flex-col gap-1.5 min-w-0 flex-1">
            <LemonSkeleton className="h-4 w-1/3" />
            <LemonSkeleton className="h-3 w-full" />
            <LemonSkeleton className="h-3 w-2/3" />
        </div>
    )
    return view === 'grid' ? (
        <div className="grid gap-3 grid-cols-1 @xl:grid-cols-2 @3xl:grid-cols-3" aria-busy>
            {Array.from({ length: 6 }, (_, index) => (
                <div key={index} className="flex flex-col border border-primary rounded-lg overflow-hidden">
                    <LemonSkeleton className="aspect-video w-full rounded-none" />
                    <div className="p-3">{lines}</div>
                </div>
            ))}
        </div>
    ) : (
        <div className="flex flex-col gap-2" aria-busy>
            {Array.from({ length: 5 }, (_, index) => (
                <div key={index} className="flex items-center gap-3 border border-primary rounded-lg p-2">
                    <LemonSkeleton className="w-28 aspect-video shrink-0" />
                    {lines}
                </div>
            ))}
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
        view,
        page,
        pageCount,
        pageResults,
        pageStartIndex,
        pageEndIndex,
    } = useValues(logic)
    const { setPage, setView } = useActions(logic)

    if (!searching && (!results || results.length === 0)) {
        return null
    }
    const returnParams = searchReturnParams(searchedQuery ?? '', scannerId, sourceObservationId)
    const tierOf = (result: ObservationSearchResultApi): Tier | null =>
        topMatchDistanceCutoff === null ? null : result.distance <= topMatchDistanceCutoff ? 'top' : 'other'
    return (
        <div className="flex flex-col">
            <div className="flex items-center gap-2 mb-1">
                <span className="text-xs text-secondary">
                    {searching || !results
                        ? 'Searching…'
                        : `${truncated ? 'Showing the top ' : ''}${pluralize(results.length, 'match', 'matches')}, best first`}
                </span>
                <LemonSegmentedButton<ResultsView>
                    size="xsmall"
                    className="ml-auto"
                    value={view}
                    onChange={setView}
                    options={[
                        {
                            value: 'grid',
                            icon: <IconGridMasonry />,
                            tooltip: 'Thumbnails',
                            'data-attr': 'vision-search-view-grid',
                        },
                        { value: 'list', icon: <IconList />, tooltip: 'List', 'data-attr': 'vision-search-view-list' },
                    ]}
                />
            </div>
            <div className="flex flex-col gap-3">
                {searching || !results ? (
                    <ResultsSkeleton view={view} />
                ) : view === 'grid' ? (
                    <div className="grid gap-3 grid-cols-1 @xl:grid-cols-2 @3xl:grid-cols-3">
                        {pageResults.map((result) => (
                            <MomentCard
                                key={result.observation.id}
                                result={result}
                                searchedQuery={searchedQuery ?? ''}
                                returnParams={returnParams}
                                tier={tierOf(result)}
                            />
                        ))}
                    </div>
                ) : (
                    tierGroups(pageResults, tierOf).map((group) => (
                        <div key={group.tier ?? 'all'} className="flex flex-col gap-2">
                            {group.tier && <TierHeading tier={group.tier} />}
                            {group.results.map((result) => (
                                <MomentRow
                                    key={result.observation.id}
                                    result={result}
                                    searchedQuery={searchedQuery ?? ''}
                                    returnParams={returnParams}
                                />
                            ))}
                        </div>
                    ))
                )}
                {!searching && results && (
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
                )}
            </div>
        </div>
    )
}
