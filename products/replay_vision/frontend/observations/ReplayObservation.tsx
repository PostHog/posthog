import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Suspense, useEffect, useRef, useState } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonCard, Link, Spinner } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { LabeledRow } from '../components/LabeledRow'
import { readResult } from '../components/ObservationCard'
import { ObservationProgressBar } from '../components/ObservationProgressBar'
import { ObservationPrompt } from '../components/ObservationPrompt'
import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { configFromSnapshot } from '../replay_scanners/types'
import { scannerLabel } from '../utils/observation'
import { parseNumericParam } from '../utils/urlParams'
import { ObservationDetails } from './ObservationDetails'
import { ObservationFacts } from './ObservationFacts'
import { ObservationHeadline } from './ObservationHeadline'
import { ObservationLabelControl } from './ObservationLabelControl'
import { ObservationPinnedProperties } from './ObservationPinnedProperties'
import { ObservationReasoning } from './ObservationReasoning'
import { ObservationRecordingUnavailable } from './ObservationRecordingUnavailable'
import { ObservationShareButton } from './ObservationShareButton'
import { ObservationUnsuccessfulScan } from './ObservationUnsuccessfulScan'
import {
    neighborFilterParams,
    observationDetailUrl,
    observationOriginParams,
    replayObservationLogic,
    scannerReturnParams,
} from './replayObservationLogic'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

const ObservationRecording = lazyWithRetry(() => import('./ObservationRecording'))

export const scene: SceneExport = {
    component: ReplayObservationSceneComponent,
    logic: replayObservationSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ReplayObservationSceneComponent(): JSX.Element {
    const { observationId } = useValues(replayObservationSceneLogic)
    const { searchParams } = useValues(router)
    const playerRef = useRef<HTMLDivElement>(null)
    const [pendingSeek, setPendingSeek] = useState<{ ms: number; trigger: number } | null>(null)
    // A shared link carries the moment the sharer was watching, in seconds, the same way a recording link does.
    const sharedStartSeconds = parseNumericParam(searchParams.t)

    // Open a shared link where its sender left off. A seek belongs to one observation, so both the shared
    // start and any citation seek are dropped once prev/next moves to a sibling.
    useEffect(() => {
        if (sharedStartSeconds !== null && sharedStartSeconds >= 0) {
            setPendingSeek({ ms: sharedStartSeconds * 1000, trigger: Date.now() })
        } else {
            setPendingSeek(null)
        }
    }, [observationId, sharedStartSeconds])

    const observationLogic = replayObservationLogic({ id: observationId })
    useAttachedLogic(observationLogic, replayObservationSceneLogic)

    const { observation, observationLoading, retrying, previousObservationId, nextObservationId, neighborsPending } =
        useValues(observationLogic)
    const { retryObservation } = useActions(observationLogic)

    // Filters carried over from the scanner's observations table; preserved on prev/next so
    // navigation (and the server-computed neighbor ids) stay within the filtered list.
    const neighborParams = neighborFilterParams(searchParams)
    const neighborsFiltered = Object.keys(neighborParams).some((key) => key !== 'order_by')
    // Prev/next keeps the return params too, so back still lands on the list view (or the watch feed)
    // the reader came from.
    const observationUrl = (id: string): string =>
        observationDetailUrl(id, {
            ...neighborParams,
            ...scannerReturnParams(searchParams),
            ...observationOriginParams(searchParams),
        })

    useKeyboardHotkeys(
        {
            j: {
                action: () => nextObservationId && router.actions.push(observationUrl(nextObservationId)),
                disabled: !nextObservationId,
            },
            k: {
                action: () => previousObservationId && router.actions.push(observationUrl(previousObservationId)),
                disabled: !previousObservationId,
            },
        },
        [nextObservationId, previousObservationId, searchParams]
    )

    if (observationLoading && !observation) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    if (!observation) {
        return (
            <SceneContent>
                <SceneTitleSection name="Observation not found" resourceType={{ type: 'replay_vision' }} />
                <p className="text-muted">
                    This observation either doesn't exist or you don't have access to it.{' '}
                    <Link to={urls.replayVision()}>Go to Replay vision</Link>.
                </p>
            </SceneContent>
        )
    }

    const playerKey = `vision-observation-${observation.id}`
    const snapshot = observation.scanner_snapshot
    const result = readResult(observation)
    const reasoning = result && typeof result.reasoning === 'string' ? result.reasoning : null
    const reasoningSegments = result?.reasoning_segments
    const scannerType = snapshot?.scanner_type
    const scannerName = scannerLabel(observation)
    const prompt = configFromSnapshot(snapshot)?.prompt ?? null

    const seekEmbeddedPlayer = (ms: number): void => {
        setPendingSeek({ ms, trigger: Date.now() })
        // On narrow screens the player sits below the result, so bring it into view with the seek.
        playerRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={scannerName}
                description={observation.recording_subject_email ?? undefined}
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <>
                        <LemonButton
                            icon={<IconArrowLeft />}
                            type="secondary"
                            size="small"
                            loading={neighborsPending}
                            to={previousObservationId ? observationUrl(previousObservationId) : undefined}
                            disabledReason={
                                previousObservationId || neighborsPending
                                    ? undefined
                                    : neighborsFiltered
                                      ? 'No previous observation matching your filters'
                                      : 'No newer observation'
                            }
                            tooltip={
                                <>
                                    {neighborsFiltered
                                        ? 'Previous observation matching your filters'
                                        : 'Previous (newer) observation for this scanner'}{' '}
                                    <KeyboardShortcut k />
                                </>
                            }
                            data-attr="vision-observation-prev"
                        >
                            Previous
                        </LemonButton>
                        <LemonButton
                            sideIcon={<IconArrowRight />}
                            type="secondary"
                            size="small"
                            loading={neighborsPending}
                            to={nextObservationId ? observationUrl(nextObservationId) : undefined}
                            disabledReason={
                                nextObservationId || neighborsPending
                                    ? undefined
                                    : neighborsFiltered
                                      ? 'No next observation matching your filters'
                                      : 'No older observation'
                            }
                            tooltip={
                                <>
                                    {neighborsFiltered
                                        ? 'Next observation matching your filters'
                                        : 'Next (older) observation for this scanner'}{' '}
                                    <KeyboardShortcut j />
                                </>
                            }
                            data-attr="vision-observation-next"
                        >
                            Next
                        </LemonButton>
                        <ObservationShareButton
                            observationId={observation.id}
                            sessionRecordingId={observation.session_id}
                            playerKey={playerKey}
                        />
                        <ReplayVisionFeedbackButton />
                    </>
                }
            />

            <div className="@container">
                <div className="grid grid-cols-1 gap-4 items-start @4xl:grid-cols-[minmax(20rem,1fr)_minmax(0,2fr)]">
                    <div className="flex flex-col gap-4 min-w-0">
                        <section className="border rounded p-4 bg-surface-primary flex flex-col gap-4">
                            {/* Only a finished scan answered the prompt, so the question shows beside its answer. */}
                            {prompt && observation.status === 'succeeded' && (
                                <ObservationPrompt
                                    prompt={prompt}
                                    question={observation.prompt_question}
                                    size="medium"
                                />
                            )}

                            <ObservationUnsuccessfulScan
                                observation={observation}
                                retrying={retrying}
                                onRetry={() => retryObservation()}
                            />

                            {observation.status === 'succeeded' && snapshot && result && (
                                <>
                                    {/* The answer and its evidence sit closer to each other than to the rest. */}
                                    <div className="flex flex-col gap-2">
                                        <ObservationHeadline observation={observation} onSeek={seekEmbeddedPlayer} />
                                        {scannerType !== 'summarizer' && reasoning && (
                                            <LabeledRow label="Reasoning" size="medium">
                                                <ObservationReasoning
                                                    reasoning={reasoning}
                                                    segments={reasoningSegments}
                                                    onSeek={seekEmbeddedPlayer}
                                                />
                                            </LabeledRow>
                                        )}
                                    </div>
                                    <ObservationLabelControl
                                        observationId={observation.id}
                                        initialLabel={observation.label}
                                    />
                                </>
                            )}

                            {(observation.status === 'pending' || observation.status === 'running') && (
                                <ObservationProgressBar
                                    observationId={observation.id}
                                    sessionId={observation.session_id}
                                />
                            )}

                            <div className="border-t pt-3">
                                <ObservationFacts observation={observation} />
                            </div>
                            <div className="border-t pt-3">
                                <ObservationPinnedProperties sessionId={observation.session_id} />
                            </div>
                            <div className="border-t pt-3">
                                <ObservationDetails observation={observation} />
                            </div>
                        </section>
                    </div>

                    {/* 16:10 leaves the player's top bar on top of a 16:9 frame, the shape of most recordings. */}
                    <div ref={playerRef} className="@container/player min-w-0 @4xl:sticky @4xl:top-4">
                        <LemonCard
                            className="overflow-hidden p-0 h-[min(62.5cqw,calc(100vh-8rem))]"
                            hoverEffect={false}
                        >
                            {/* Lazy, so the result renders before the player's code arrives. */}
                            <Suspense fallback={<Spinner className="m-4" />}>
                                <ObservationRecording
                                    playerKey={playerKey}
                                    sessionRecordingId={observation.session_id}
                                    pendingSeek={pendingSeek}
                                    unavailable={<ObservationRecordingUnavailable observation={observation} />}
                                />
                            </Suspense>
                        </LemonCard>
                    </div>
                </div>
            </div>
        </SceneContent>
    )
}

export default ReplayObservationSceneComponent
