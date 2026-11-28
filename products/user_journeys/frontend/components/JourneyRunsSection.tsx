import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import type { JourneyApi } from '../generated/api.schemas'
import {
    RUNS_PAGE_SIZE,
    describeFailedStep,
    isRunActive,
    journeyRunStartUrl,
    originOf,
    runDurationSeconds,
    runOrigin,
} from '../journeyRuns'
import { userJourneyRunsLogic } from '../userJourneyRunsLogic'
import { JourneyRunSource } from './JourneyRunSource'
import { JourneyRunStatusTag } from './JourneyRunStatusTag'
import { RunJourneyButton } from './RunJourneyButton'

const NOT_RUNNABLE_REASON = 'Add a start URL to the journey, or make its first step an exact pageview of a full URL.'

export function JourneyRunsSection({
    journeyId,
    journey,
}: {
    journeyId: string
    journey: JourneyApi | null
}): JSX.Element {
    const logic = userJourneyRunsLogic({ journeyId })
    const { runs, showRunsLoading, runsLoadFailed, page, runConflict, activeRun } = useValues(logic)
    const { loadRuns, setPage } = useActions(logic)

    const startUrl = journey ? journeyRunStartUrl(journey) : null
    const defaultOrigin = startUrl ? originOf(startUrl) : null
    const notRunnable = journey !== null && startUrl === null

    return (
        <SceneSection
            title="Runs"
            description="A browser follows the journey's steps on your site and saves a screenshot of each one, so you can see when a change breaks the flow."
            actions={
                <RunJourneyButton
                    journeyId={journeyId}
                    defaultOrigin={defaultOrigin}
                    disabledReason={!journey ? 'Loading the journey' : notRunnable ? NOT_RUNNABLE_REASON : null}
                />
            }
        >
            {notRunnable ? (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Edit journey',
                        to: urls.userJourneyEdit(journeyId),
                        'data-attr': 'user-journey-runs-edit',
                    }}
                >
                    A run needs a page to start from. {NOT_RUNNABLE_REASON}
                </LemonBanner>
            ) : null}

            {runConflict ? (
                <LemonBanner
                    type="warning"
                    action={
                        activeRun
                            ? {
                                  children: 'View run',
                                  to: urls.userJourneyRun(journeyId, activeRun.id),
                                  'data-attr': 'user-journey-runs-view-active',
                              }
                            : undefined
                    }
                >
                    This journey already has a run in progress. Its result shows here when it finishes.
                </LemonBanner>
            ) : null}

            {runsLoadFailed && runs === null ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadRuns, 'data-attr': 'user-journey-runs-retry' }}
                >
                    Couldn't load the runs of this journey. Check your connection and try again.
                </LemonBanner>
            ) : runs !== null && runs.count === 0 ? (
                <div
                    className="border border-dashed rounded p-6 flex flex-col gap-1 items-center text-center"
                    data-attr="user-journey-runs-empty"
                >
                    <span className="font-semibold">No runs yet</span>
                    <span className="text-secondary max-w-160">
                        A run opens {defaultOrigin ?? 'your site'} in a browser and follows each step. A step fails when
                        its element is missing, hidden, cut off by its container, or covered by another element. Each
                        run compares its screenshots with the last run that passed.
                    </span>
                </div>
            ) : (
                <LemonTable
                    dataSource={runs?.results ?? []}
                    loading={showRunsLoading}
                    loadingSkeletonRows={3}
                    rowKey="id"
                    nouns={['run', 'runs']}
                    data-attr="user-journey-runs-table"
                    pagination={{
                        controlled: true,
                        pageSize: RUNS_PAGE_SIZE,
                        currentPage: page + 1,
                        entryCount: runs?.count,
                        useUrl: false,
                        onBackward: page > 0 ? () => setPage(page - 1) : undefined,
                        onForward:
                            runs && (page + 1) * RUNS_PAGE_SIZE < runs.count ? () => setPage(page + 1) : undefined,
                    }}
                    columns={[
                        {
                            title: 'Result',
                            key: 'status',
                            render: (_, run) => {
                                return (
                                    <div className="flex flex-col gap-1 items-start py-1 min-w-0">
                                        <Link
                                            to={urls.userJourneyRun(journeyId, run.id)}
                                            data-attr="user-journey-runs-row-link"
                                        >
                                            <JourneyRunStatusTag status={run.status} />
                                        </Link>
                                        {run.status === 'failed' && run.failed_step_index !== null ? (
                                            <span className="text-xs text-danger">
                                                {describeFailedStep(run.failed_step_index, run.failure_reason)}
                                            </span>
                                        ) : run.status === 'errored' && run.error ? (
                                            <span className="text-xs text-secondary line-clamp-2" title={run.error}>
                                                {run.error}
                                            </span>
                                        ) : null}
                                    </div>
                                )
                            },
                        },
                        {
                            title: 'Started by',
                            key: 'trigger',
                            render: (_, run) => <JourneyRunSource run={run} />,
                        },
                        {
                            title: 'Site',
                            key: 'origin',
                            render: (_, run) => {
                                const origin = runOrigin(run) ?? defaultOrigin
                                return origin ? (
                                    <span className="font-mono text-xs truncate block max-w-60" title={origin}>
                                        {origin}
                                    </span>
                                ) : null
                            },
                        },
                        {
                            title: 'Started',
                            key: 'created_at',
                            render: (_, run) => <TZLabel time={run.created_at} />,
                        },
                        {
                            title: 'Duration',
                            key: 'duration',
                            align: 'right',
                            render: (_, run) => {
                                const seconds = runDurationSeconds(run)
                                return seconds !== null ? (
                                    <span translate="no">{humanFriendlyDuration(seconds)}</span>
                                ) : isRunActive(run.status) ? (
                                    <span className="text-secondary whitespace-nowrap">In progress</span>
                                ) : null
                            },
                        },
                    ]}
                />
            )}
        </SceneSection>
    )
}
