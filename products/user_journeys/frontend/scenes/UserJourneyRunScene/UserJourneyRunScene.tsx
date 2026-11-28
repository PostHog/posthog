import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { JourneyRunSource } from '../../components/JourneyRunSource'
import { JourneyRunStatusTag } from '../../components/JourneyRunStatusTag'
import { JourneyRunStepItem } from '../../components/JourneyRunStepItem'
import { isRunActive, runDurationSeconds, runOrigin } from '../../journeyRuns'
import { UserJourneyRunLogicProps, userJourneyRunLogic } from '../../userJourneyRunLogic'

export const scene: SceneExport<UserJourneyRunLogicProps> = {
    component: UserJourneyRunScene,
    logic: userJourneyRunLogic,
    paramsToProps: ({ params: { id, runId } }) => ({ id, runId }),
}

function MetaItem({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-xs text-secondary">{label}</span>
            <div className="min-w-0">{children}</div>
        </div>
    )
}

export function UserJourneyRunScene({ id, runId }: UserJourneyRunLogicProps): JSX.Element {
    const userJourneysEnabled = useFeatureFlag('USER_JOURNEYS')
    const logic = userJourneyRunLogic({ id, runId })
    const { run, runLoadError, summary, screenshotUrls, journey } = useValues(logic)
    const { loadRun } = useActions(logic)

    if (!userJourneysEnabled || (runLoadError === 'not_found' && !run)) {
        return <NotFound object={userJourneysEnabled ? 'journey run' : 'page'} />
    }

    if (runLoadError === 'error' && !run) {
        return (
            <SceneContent>
                <SceneTitleSection name="Journey run" resourceType={{ type: 'insight/paths' }} />
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadRun, 'data-attr': 'user-journey-run-retry' }}
                >
                    Couldn't load this run. Check your connection and try again.
                </LemonBanner>
            </SceneContent>
        )
    }

    const origin = run ? runOrigin(run) : null
    const duration = run ? runDurationSeconds(run) : null

    return (
        <SceneContent>
            <SceneTitleSection
                name={journey ? `Run of ${journey.name}` : 'Journey run'}
                isLoading={!run}
                resourceType={{ type: 'insight/paths' }}
            />

            {run ? (
                <div className="flex flex-col gap-4" data-attr="user-journey-run-header">
                    <div className="flex items-center gap-2 flex-wrap">
                        <JourneyRunStatusTag status={run.status} />
                        <span className="font-semibold text-base" data-attr="user-journey-run-summary">
                            {summary}
                        </span>
                    </div>
                    <div className="grid grid-cols-2 @min-[48rem]/main-content:grid-cols-4 @min-[72rem]/main-content:grid-cols-6 gap-x-6 gap-y-3">
                        <MetaItem label="Started by">
                            <JourneyRunSource run={run} />
                        </MetaItem>
                        <MetaItem label="Site">
                            {origin ? (
                                <span className="font-mono text-xs truncate block" title={run.start_url ?? origin}>
                                    {origin}
                                </span>
                            ) : (
                                <span className="text-secondary">Not opened yet</span>
                            )}
                        </MetaItem>
                        <MetaItem label="Viewport">
                            <span translate="no">
                                {run.viewport_width} × {run.viewport_height}
                            </span>
                        </MetaItem>
                        <MetaItem label="Started">
                            <TZLabel time={run.started_at ?? run.created_at} />
                        </MetaItem>
                        <MetaItem label="Duration">
                            {duration !== null ? (
                                <span translate="no">{humanFriendlyDuration(duration)}</span>
                            ) : (
                                <span className="text-secondary">
                                    {isRunActive(run.status) ? 'In progress' : 'Unknown'}
                                </span>
                            )}
                        </MetaItem>
                        <MetaItem label="Compared with">
                            <span className="text-secondary">
                                {isRunActive(run.status)
                                    ? 'Picked when the run ends'
                                    : run.baseline_run_id
                                      ? 'The last run that passed'
                                      : 'No earlier run passed'}
                            </span>
                        </MetaItem>
                    </div>
                    {run.error ? (
                        <LemonBanner type="error">
                            <span className="font-semibold">The run couldn't finish. </span>
                            <span>{run.error}</span>
                        </LemonBanner>
                    ) : null}
                    {screenshotUrls === 'unavailable' ? (
                        <LemonBanner
                            type="warning"
                            action={{ children: 'Reload', onClick: loadRun, 'data-attr': 'user-journey-run-reload' }}
                        >
                            Some screenshots couldn't load. Reload the run to try again.
                        </LemonBanner>
                    ) : null}
                </div>
            ) : (
                <LemonSkeleton className="h-24" />
            )}

            <SceneDivider />

            <SceneSection
                title="Steps"
                description="What the browser found at each step. A failed step stops the run, so later steps are skipped."
            >
                {!run ? (
                    <LemonSkeleton className="h-60" />
                ) : isRunActive(run.status) ? (
                    <div className="border border-dashed rounded p-6 flex items-center justify-center gap-2 text-secondary">
                        <Spinner />
                        <span>
                            {run.status === 'pending'
                                ? 'Waiting for a browser. The steps show here when the run finishes.'
                                : 'The browser is following the steps. They show here when the run finishes.'}
                        </span>
                    </div>
                ) : run.steps.length === 0 ? (
                    <div className="border border-dashed rounded p-6 text-center text-secondary">
                        The run ended before it reached the first step.
                    </div>
                ) : (
                    <ol className="flex flex-col list-none p-0 m-0" data-attr="user-journey-run-steps">
                        {run.steps.map((step, position) => (
                            <JourneyRunStepItem
                                key={step.index}
                                id={id}
                                runId={runId}
                                run={run}
                                step={step}
                                isLast={position === run.steps.length - 1}
                            />
                        ))}
                    </ol>
                )}
            </SceneSection>
        </SceneContent>
    )
}
