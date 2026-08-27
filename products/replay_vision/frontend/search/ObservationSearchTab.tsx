import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { ObservationResultSummary } from '../components/ObservationCard'
import { ScannerTypeBadge } from '../components/ScannerTypeBadge'
import type { ObservationSearchResultApi } from '../generated/api.schemas'
import { scannerLabel } from '../utils/observation'
import { observationSearchLogic } from './observationSearchLogic'
import { snippetSegments } from './snippetSegments'

const EXAMPLE_QUERIES = ['users who got stuck and gave up', 'rage clicking out of frustration']

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
                {observation.recording_subject_email && (
                    <span className="text-xs text-muted truncate">{observation.recording_subject_email}</span>
                )}
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

export function ObservationSearchTab({ scannerId }: { scannerId: string | null }): JSX.Element {
    const logic = observationSearchLogic({ scannerId })
    const { query, results, searching, searchedQuery, strongMatchDistanceCutoff, truncated } = useValues(logic)
    const { setQuery, search } = useActions(logic)
    const crossScanner = scannerId === null

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
                    onPressEnter={() => !searching && search()}
                    autoFocus
                    data-attr="vision-search-query"
                />
                <LemonButton
                    type="primary"
                    onClick={() => search()}
                    loading={searching}
                    disabledReason={!query.trim() ? 'Describe what to look for first' : undefined}
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
                    <div className="text-center text-muted pt-8 flex flex-col gap-3">
                        <div>
                            {crossScanner
                                ? 'Search everything your scanners have observed, ranked by how well it matches.'
                                : 'Search everything this scanner has observed, ranked by how well it matches.'}
                        </div>
                        <div className="flex items-center justify-center gap-2 flex-wrap">
                            <span>Try</span>
                            {EXAMPLE_QUERIES.map((example) => (
                                <LemonButton
                                    key={example}
                                    type="secondary"
                                    size="small"
                                    onClick={() => {
                                        setQuery(example)
                                        search()
                                    }}
                                    data-attr="vision-search-example"
                                >
                                    {example}
                                </LemonButton>
                            ))}
                        </div>
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
