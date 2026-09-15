import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconPlay } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { ObservationResultSummary } from '../components/ObservationCard'
import { ScannerOutputBadge } from '../components/ScannerOutputBadge'
import type { ObservationSearchResultApi, ReplayObservationApi } from '../generated/api.schemas'
import { observationDetailUrl } from '../observations/replayObservationLogic'
import { ReplayScannerTab } from '../replay_scanners/replayScannerSceneLogic'
import { stripCitations } from '../utils/citations'
import { hasScannerPage, scannerLabel } from '../utils/observation'
import { firstCitedTimestampMs, watchMomentUrl } from './observationQueries'
import { type ObservationSearchLogicProps, SEARCH_PAGE_SIZE, observationSearchLogic } from './observationSearchLogic'
import { snippetSegments } from './snippetSegments'

function countLabel(count: number, truncated: boolean): string {
    if (truncated) {
        return `Showing the top ${count === 1 ? 'match' : `${count} matches`}, best first`
    }
    return `${count === 1 ? '1 match' : `${count} matches`}, best first`
}

// Email, then distinct id, then session id: whichever identifies the recorded person first.
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

function SearchResultCard({
    result,
    searchedQuery,
    crossScanner,
}: {
    result: ObservationSearchResultApi
    searchedQuery: string
    crossScanner: boolean
}): JSX.Element {
    const observation = result.observation
    const snapshot = observation.scanner_snapshot
    const detailUrl = observationDetailUrl(observation.id, crossScanner ? {} : { tab: ReplayScannerTab.Observations })
    const citedMs = firstCitedTimestampMs(observation)
    // The snippet has no seek controls to spend the stored `(t 12)` markers on.
    const snippet = stripCitations(result.matched_content)
    return (
        <div
            className="border border-secondary rounded p-3 bg-surface-primary space-y-2 text-primary"
            data-attr="vision-search-result"
        >
            <div className="flex items-center gap-2 min-w-0">
                {crossScanner && (
                    <>
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
                    </>
                )}
                <SubjectLabel observation={observation} />
                <span className="ml-auto shrink-0 text-xs text-muted">
                    <TZLabel time={observation.created_at} />
                </span>
            </div>
            {snippet && (
                <div className="text-sm text-secondary line-clamp-2">
                    {snippetSegments(snippet, searchedQuery).map((segment, index) =>
                        segment.highlighted ? (
                            <span key={index} className="font-semibold text-secondary">
                                {segment.text}
                            </span>
                        ) : (
                            <span key={index}>{segment.text}</span>
                        )
                    )}
                </div>
            )}
            <ObservationResultSummary observation={observation} />
            {/* leading-none stops the icon in the second link from pushing its text off the first's baseline. */}
            <div className="flex items-center gap-3 text-xs leading-none">
                <Link to={detailUrl} className="inline-flex items-center" data-attr="vision-search-result-detail">
                    View details
                </Link>
                <Link
                    to={watchMomentUrl(observation)}
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
        <div className="flex items-baseline gap-2 pt-2 first:pt-0">
            <span className="font-semibold text-sm">{tier === 'top' ? 'Top matches' : 'Other matches'}</span>
            <span className="text-muted text-xs">
                {tier === 'top' ? 'Closest to what you described.' : 'Related, but further from what you described.'}
            </span>
        </div>
    )
}

export function SearchResults({
    crossScanner,
    ...logicProps
}: ObservationSearchLogicProps & { crossScanner: boolean }): JSX.Element | null {
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
    // Tiers only across scanners: one scanner writes in one voice, so the split rarely separates anything there.
    const cutoff = crossScanner ? topMatchDistanceCutoff : null
    const tierOf = (result: ObservationSearchResultApi): Tier | null =>
        cutoff === null ? null : result.distance <= cutoff ? 'top' : 'other'
    return (
        <div className={clsx('flex flex-col gap-3', searching && 'opacity-50 pointer-events-none')}>
            <div className="text-xs text-secondary">{countLabel(results.length, truncated)}</div>
            <div className="flex flex-col gap-2">
                {pageResults.map((result, index) => {
                    const tier = tierOf(result)
                    const startsTier = tier !== null && (index === 0 || tierOf(pageResults[index - 1]) !== tier)
                    return (
                        <Fragment key={result.observation.id}>
                            {startsTier && <TierHeading tier={tier} />}
                            <SearchResultCard
                                result={result}
                                searchedQuery={searchedQuery ?? ''}
                                crossScanner={crossScanner}
                            />
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
