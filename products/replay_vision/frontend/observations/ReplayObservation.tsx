import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Suspense, useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonCard, Link, Spinner } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { CitedMarkdown } from '../components/CitedMarkdown'
import { LabeledRow } from '../components/LabeledRow'
import { readResult } from '../components/ObservationCard'
import { ObservationProgressBar } from '../components/ObservationProgressBar'
import { ObservationRetryButton } from '../components/ObservationRetryButton'
import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { PromptPreview } from '../replay_scanners/components/PromptPreview'
import {
    configFromSnapshot,
    failureKindDescription,
    ineligibleKindDescription,
    parseFailureReason,
    parseIneligibleReason,
    SUCCEEDED_OUTPUT_LABEL,
} from '../replay_scanners/types'
import { hasScannerPage, scannerLabel } from '../utils/observation'
import { parseNumericParam } from '../utils/urlParams'
import { ObservationDetails } from './ObservationDetails'
import { ObservationFacts } from './ObservationFacts'
import { ObservationHeadline } from './ObservationHeadline'
import { ObservationLabelControl } from './ObservationLabelControl'
import { observationLabelLogic } from './observationLabelLogic'
import { ObservationPinnedProperties } from './ObservationPinnedProperties'
import { ObservationShareButton } from './ObservationShareButton'
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

/** Rating happens here, not in the Calibration tab, so a rater never sees the recommendation it feeds. */
function CalibrationEntryPoint({ observation }: { observation: ReplayObservationApi }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    // Read the rating from the control's logic rather than the loaded observation, which keeps the
    // label it was fetched with. The control alongside builds this same keyed logic.
    const { label } = useValues(
        observationLabelLogic({ observationId: observation.id, initialLabel: observation.label })
    )
    // Multivariate flags resolve to the variant key, and "control" is truthy, so compare rather than coerce.
    if (
        !label ||
        !hasScannerPage(observation) ||
        featureFlags[FEATURE_FLAGS.REPLAY_VISION_CALIBRATION_ENTRY_POINT] !== 'test'
    ) {
        return null
    }
    return (
        <p className="text-sm text-muted m-0">
            <Link
                to={`${urls.replayVision(observation.scanner_id)}?tab=calibration`}
                data-attr="vision-observation-calibration-entry-point"
            >
                Rate more results for this scanner
            </Link>{' '}
            to get a config recommendation from your ratings.
        </p>
    )
}

export function ReplayObservationSceneComponent(): JSX.Element {
    const { observationId } = useValues(replayObservationSceneLogic)
    const { searchParams } = useValues(router)
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
    const ineligibleParsed =
        observation.status === 'ineligible' && observation.error_reason
            ? parseIneligibleReason(observation.error_reason)
            : null
    const ineligibleMessage = ineligibleParsed ? ineligibleParsed.message || null : observation.error_reason || null
    const failedParsed =
        observation.status === 'failed' && observation.error_reason
            ? parseFailureReason(observation.error_reason)
            : null
    const failedMessage = failedParsed ? failedParsed.message || null : observation.error_reason || null

    const seekEmbeddedPlayer = (ms: number): void => setPendingSeek({ ms, trigger: Date.now() })

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
                            {/* A scan that failed or never ran answered nothing, so the question alone adds no context. */}
                            {prompt && observation.status !== 'failed' && observation.status !== 'ineligible' && (
                                <LabeledRow label="Prompt">
                                    <PromptPreview prompt={prompt} dataAttr="vision-observation-show-prompt" />
                                </LabeledRow>
                            )}

                            {observation.status === 'failed' && observation.error_reason && (
                                <div className="flex flex-col gap-3">
                                    <div className="flex flex-col gap-1">
                                        <span className="text-2xl font-bold text-danger">Scan failed</span>
                                        <p className="text-sm text-default m-0 leading-snug">
                                            {failedParsed
                                                ? failureKindDescription(failedParsed.kind)
                                                : observation.error_reason}
                                        </p>
                                    </div>
                                    {failedParsed && failedMessage && (
                                        <LabeledRow label="Error">
                                            <p className="text-sm text-default m-0 leading-snug font-mono">
                                                {failedMessage}
                                            </p>
                                        </LabeledRow>
                                    )}
                                    <div>
                                        <ObservationRetryButton
                                            status={observation.status}
                                            errorReason={observation.error_reason}
                                            onRetry={() => retryObservation()}
                                            loading={retrying}
                                            emphasis="primary"
                                            size="small"
                                            dataAttr="vision-observation-detail-retry"
                                        />
                                    </div>
                                </div>
                            )}

                            {observation.status === 'ineligible' && observation.error_reason && (
                                <div className="flex flex-col gap-3">
                                    <div className="flex flex-col gap-1">
                                        <span className="text-2xl font-bold text-muted">Not scanned</span>
                                        <p className="text-sm text-default m-0 leading-snug">
                                            {ineligibleParsed
                                                ? ineligibleKindDescription(ineligibleParsed.kind)
                                                : observation.error_reason}
                                        </p>
                                    </div>
                                    {ineligibleParsed && ineligibleMessage && (
                                        <LabeledRow label="More info">
                                            <p className="text-sm text-default m-0 leading-snug">{ineligibleMessage}</p>
                                        </LabeledRow>
                                    )}
                                    <div>
                                        <ObservationRetryButton
                                            status={observation.status}
                                            errorReason={observation.error_reason}
                                            onRetry={() => retryObservation()}
                                            loading={retrying}
                                            size="small"
                                            dataAttr="vision-observation-detail-retry"
                                        />
                                    </div>
                                </div>
                            )}

                            {observation.status === 'succeeded' && snapshot && result && (
                                <>
                                    <LabeledRow
                                        label={
                                            scannerType === 'classifier'
                                                ? 'Assigned categories'
                                                : scannerType
                                                  ? SUCCEEDED_OUTPUT_LABEL[scannerType]
                                                  : ''
                                        }
                                    >
                                        <ObservationHeadline observation={observation} onSeek={seekEmbeddedPlayer} />
                                    </LabeledRow>
                                    {scannerType !== 'summarizer' && reasoning && (
                                        <LabeledRow label="Reasoning">
                                            <CitedMarkdown
                                                text={reasoning}
                                                segments={reasoningSegments}
                                                onSeek={seekEmbeddedPlayer}
                                            />
                                        </LabeledRow>
                                    )}
                                    <ObservationLabelControl
                                        observationId={observation.id}
                                        initialLabel={observation.label}
                                    />
                                    <CalibrationEntryPoint observation={observation} />
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
                    <div className="@container/player min-w-0 @4xl:sticky @4xl:top-4">
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
