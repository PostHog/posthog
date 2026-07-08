import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import {
    IconArrowLeft,
    IconArrowRight,
    IconClock,
    IconCollapse,
    IconExpand,
    IconGear,
    IconInfo,
    IconRefresh,
    IconSparkles,
    IconThoughtBubble,
    IconVideoCamera,
} from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { humanFriendlyDuration, humanFriendlyMilliseconds } from 'lib/utils/durations'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { BooleanTag } from '../components/BooleanTag'
import { CardHeader } from '../components/CardHeader'
import { LabeledRow } from '../components/LabeledRow'
import {
    CitedText,
    ObservationConfidence,
    ObservationPrimaryOutput,
    ObservationStatusTag,
    readResult,
} from '../components/ObservationCard'
import { ObservationProgressBar } from '../components/ObservationProgressBar'
import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { ScannerTypeBadge } from '../components/ScannerTypeBadge'
import {
    type ClassifierScannerConfig,
    type MonitorScannerConfig,
    type ScorerScannerConfig,
    type SummarizerScannerConfig,
    configFromSnapshot,
    failureKindDescription,
    ineligibleKindDescription,
    modelLabel,
    parseFailureReason,
    parseIneligibleReason,
    type ScannerType,
} from '../replay_scanners/types'
import { ObservationLabelControl } from './ObservationLabelControl'
import { replayObservationLogic } from './replayObservationLogic'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

export const scene: SceneExport = {
    component: ReplayObservationSceneComponent,
    logic: replayObservationSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

const SUCCEEDED_OUTPUT_LABEL: Record<ScannerType, string> = {
    classifier: 'Tags',
    summarizer: 'Summary',
    monitor: 'Verdict',
    scorer: 'Score',
}

function AutoSeekToTime({
    playerKey,
    sessionRecordingId,
    ms,
    trigger,
}: {
    playerKey: string
    sessionRecordingId: string
    ms: number
    trigger: number
}): null {
    const { sessionPlayerData } = useValues(sessionRecordingPlayerLogic({ playerKey, sessionRecordingId }))
    // `start`/`end` are fresh Dayjs objects on every snapshot batch; compare epochs so deps stay stable.
    const startMs = sessionPlayerData?.start?.valueOf() ?? null
    const endMs = sessionPlayerData?.end?.valueOf() ?? null
    // Latch per-trigger so snapshot-batch arrivals don't re-seek and fight playback.
    const seekedForTrigger = useRef<number | null>(null)
    useEffect(() => {
        if (seekedForTrigger.current === trigger || startMs == null || endMs == null) {
            return
        }
        sessionRecordingPlayerLogic.findMounted({ playerKey, sessionRecordingId })?.actions.seekToTime(ms)
        seekedForTrigger.current = trigger
    }, [startMs, endMs, ms, trigger, playerKey, sessionRecordingId])
    return null
}

export function ReplayObservationSceneComponent(): JSX.Element {
    const { observationId } = useValues(replayObservationSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const qualityEnabled = !!featureFlags[FEATURE_FLAGS.REPLAY_VISION_QUALITY]
    const [recordingExpanded, setRecordingExpanded] = useState(true)
    const [pendingSeek, setPendingSeek] = useState<{ ms: number; trigger: number } | null>(null)

    // A citation seek belongs to one observation — never replay it on a sibling after prev/next navigation.
    useEffect(() => {
        setPendingSeek(null)
    }, [observationId])

    const observationLogic = replayObservationLogic({ id: observationId })
    useAttachedLogic(observationLogic, replayObservationSceneLogic)

    const { observation, observationLoading, retrying } = useValues(observationLogic)
    const { retryObservation } = useActions(observationLogic)

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
                    <Link to={urls.replayVision()}>Back to scanners</Link>.
                </p>
            </SceneContent>
        )
    }

    const snapshot = observation.scanner_snapshot
    const result = readResult(observation)
    const reasoning = result && typeof result.reasoning === 'string' ? result.reasoning : null
    const reasoningSegments = result?.reasoning_segments
    const scannerType = snapshot?.scanner_type
    const scannerName = snapshot?.name || 'Scanner'
    const triggerLabel = observation.triggered_by === 'on_demand' ? 'On demand' : 'Schedule'
    const snapshotConfig = configFromSnapshot(snapshot)
    const prompt = snapshotConfig?.prompt ?? null
    const summarizerConfig = scannerType === 'summarizer' ? (snapshotConfig as SummarizerScannerConfig | null) : null
    const classifierConfig = scannerType === 'classifier' ? (snapshotConfig as ClassifierScannerConfig | null) : null
    const monitorConfig = scannerType === 'monitor' ? (snapshotConfig as MonitorScannerConfig | null) : null
    const scorerConfig = scannerType === 'scorer' ? (snapshotConfig as ScorerScannerConfig | null) : null
    const summarizerLength = summarizerConfig?.length ?? null
    const classifierVocab = Array.isArray(classifierConfig?.tags) ? classifierConfig.tags : null
    const classifierMultiLabel = classifierConfig ? classifierConfig.multi_label === true : null
    const monitorAllowInconclusive = monitorConfig ? monitorConfig.allow_inconclusive === true : null
    const classifierAllowFreeform = classifierConfig ? classifierConfig.allow_freeform_tags === true : null
    const scorerMin = typeof scorerConfig?.scale?.min === 'number' ? scorerConfig.scale.min : null
    const scorerMax = typeof scorerConfig?.scale?.max === 'number' ? scorerConfig.scale.max : null
    const scorerLabel = typeof scorerConfig?.scale?.label === 'string' ? scorerConfig.scale.label : null
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
    const durationMs =
        observation.started_at && observation.completed_at
            ? dayjs(observation.completed_at).diff(observation.started_at)
            : null
    const durationLabel =
        durationMs !== null && Number.isFinite(durationMs) && durationMs >= 0
            ? durationMs < 60_000
                ? (humanFriendlyMilliseconds(durationMs) ?? null)
                : humanFriendlyDuration(durationMs / 1000)
            : null

    const seekEmbeddedPlayer = (ms: number): void => {
        if (!recordingExpanded) {
            setRecordingExpanded(true)
        }
        setPendingSeek({ ms, trigger: Date.now() })
    }

    const toggleRecordingExpanded = (): void => {
        // Collapsing discards the seek intent, or re-expanding would remount the seeker and replay it.
        if (recordingExpanded) {
            setPendingSeek(null)
        }
        setRecordingExpanded(!recordingExpanded)
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={scannerName}
                description={`Observation of session ${observation.session_id}`}
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <>
                        <LemonButton
                            icon={<IconArrowLeft />}
                            type="secondary"
                            size="small"
                            to={
                                observation.previous_observation_id
                                    ? urls.replayVisionObservation(observation.previous_observation_id)
                                    : undefined
                            }
                            disabledReason={observation.previous_observation_id ? undefined : 'No newer observation'}
                            tooltip="Previous (newer) observation for this scanner"
                            data-attr="vision-observation-prev"
                        >
                            Previous
                        </LemonButton>
                        <LemonButton
                            sideIcon={<IconArrowRight />}
                            type="secondary"
                            size="small"
                            to={
                                observation.next_observation_id
                                    ? urls.replayVisionObservation(observation.next_observation_id)
                                    : undefined
                            }
                            disabledReason={observation.next_observation_id ? undefined : 'No older observation'}
                            tooltip="Next (older) observation for this scanner"
                            data-attr="vision-observation-next"
                        >
                            Next
                        </LemonButton>
                        <ReplayVisionFeedbackButton />
                    </>
                }
            />

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconInfo />} title="Observation details" />
                    <div className="flex flex-col gap-3 text-sm">
                        <LabeledRow label="Status">
                            <ObservationStatusTag status={observation.status} />
                        </LabeledRow>
                        {result && typeof result.confidence === 'number' && (
                            <LabeledRow label="Confidence">
                                <ObservationConfidence result={result} />
                            </LabeledRow>
                        )}
                        <LabeledRow label="Triggered by">
                            {observation.triggered_by === 'on_demand' && observation.triggered_by_user ? (
                                <ProfilePicture
                                    user={{
                                        first_name: observation.triggered_by_user.first_name,
                                        last_name: observation.triggered_by_user.last_name,
                                        email: observation.triggered_by_user.email,
                                    }}
                                    size="sm"
                                    showName
                                />
                            ) : (
                                <span>{triggerLabel}</span>
                            )}
                        </LabeledRow>
                        <LabeledRow label="Session">
                            <Link
                                to={urls.sessionProfile(observation.session_id)}
                                data-attr="vision-observation-session-link"
                            >
                                {observation.session_id}
                            </Link>
                        </LabeledRow>
                        <LabeledRow label="Recording subject">
                            {observation.distinct_id ? (
                                <Link to={urls.personByDistinctId(observation.distinct_id)}>
                                    {observation.recording_subject_email ?? observation.distinct_id}
                                </Link>
                            ) : observation.recording_subject_email ? (
                                <span>{observation.recording_subject_email}</span>
                            ) : (
                                <span className="text-muted">—</span>
                            )}
                        </LabeledRow>
                    </div>
                </LemonCard>

                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconClock />} title="Lifecycle" />
                    <div className="flex flex-col gap-3 text-sm">
                        <LabeledRow label="Created at">
                            <TZLabel time={observation.created_at} />
                        </LabeledRow>
                        {observation.started_at && (
                            <LabeledRow label="Started at">
                                <TZLabel time={observation.started_at} />
                            </LabeledRow>
                        )}
                        {observation.completed_at && (
                            <LabeledRow label="Completed at">
                                <TZLabel time={observation.completed_at} />
                            </LabeledRow>
                        )}
                        {durationLabel && (
                            <LabeledRow label="Duration">
                                <span>{durationLabel}</span>
                            </LabeledRow>
                        )}
                    </div>
                </LemonCard>

                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconGear />} title="Configuration" />
                    <div className="flex flex-col gap-3 text-sm">
                        {snapshot?.model && (
                            <LabeledRow label="Model">
                                <span>{modelLabel(snapshot.model)}</span>
                            </LabeledRow>
                        )}
                        {summarizerLength && (
                            <LabeledRow label="Summary length">
                                <span className="capitalize">{summarizerLength}</span>
                            </LabeledRow>
                        )}
                        {classifierVocab && classifierVocab.length > 0 && (
                            <LabeledRow label="Vocabulary">
                                <div className="flex flex-wrap gap-1">
                                    {classifierVocab.map((tag) => (
                                        <LemonTag key={tag} type="default" size="small">
                                            {tag}
                                        </LemonTag>
                                    ))}
                                </div>
                            </LabeledRow>
                        )}
                        {monitorAllowInconclusive !== null && (
                            <LabeledRow label="Allow inconclusive verdicts">
                                <BooleanTag value={monitorAllowInconclusive} />
                            </LabeledRow>
                        )}
                        {classifierMultiLabel !== null && (
                            <LabeledRow label="Multi-label">
                                <BooleanTag value={classifierMultiLabel} />
                            </LabeledRow>
                        )}
                        {classifierAllowFreeform !== null && (
                            <LabeledRow label="Freeform tags">
                                <BooleanTag value={classifierAllowFreeform} />
                            </LabeledRow>
                        )}
                        {scorerMin !== null && (
                            <LabeledRow label="Scale minimum">
                                <span>{scorerMin}</span>
                            </LabeledRow>
                        )}
                        {scorerMax !== null && (
                            <LabeledRow label="Scale maximum">
                                <span>{scorerMax}</span>
                            </LabeledRow>
                        )}
                        {scorerLabel && (
                            <LabeledRow label="Score label">
                                <span>{scorerLabel}</span>
                            </LabeledRow>
                        )}
                        {snapshot?.emits_signals && (
                            <LabeledRow label="Signals">
                                <span>Emitted ({observation.scanner_result?.signals_count ?? 0})</span>
                            </LabeledRow>
                        )}
                    </div>
                </LemonCard>
            </div>

            <div className={scannerType === 'summarizer' ? '' : 'grid grid-cols-1 lg:grid-cols-2 gap-4'}>
                <section className="border rounded p-4 bg-surface-primary space-y-3">
                    <CardHeader icon={<IconSparkles />} title="Result" />

                    {observation.status === 'failed' && observation.error_reason && (
                        <div className="flex flex-col gap-3">
                            {scannerType && (
                                <LabeledRow label="Type">
                                    <ScannerTypeBadge scannerType={scannerType} />
                                </LabeledRow>
                            )}
                            <LabeledRow label="Reason">
                                <p className="text-sm text-default m-0 leading-snug">
                                    {failedParsed
                                        ? failureKindDescription(failedParsed.kind)
                                        : observation.error_reason}
                                </p>
                            </LabeledRow>
                            {failedParsed && failedMessage && (
                                <LabeledRow label="Details">
                                    <p className="text-sm text-default m-0 leading-snug font-mono">{failedMessage}</p>
                                </LabeledRow>
                            )}
                            <div>
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.SessionRecording}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        icon={<IconRefresh />}
                                        onClick={() => retryObservation()}
                                        loading={retrying}
                                        data-attr="vision-observation-detail-retry"
                                    >
                                        Retry scan
                                    </LemonButton>
                                </AccessControlAction>
                            </div>
                        </div>
                    )}

                    {observation.status === 'ineligible' && observation.error_reason && (
                        <div className="flex flex-col gap-3">
                            {scannerType && (
                                <LabeledRow label="Type">
                                    <ScannerTypeBadge scannerType={scannerType} />
                                </LabeledRow>
                            )}
                            <LabeledRow label="Reason">
                                <p className="text-sm text-default m-0 leading-snug">
                                    {ineligibleParsed
                                        ? ineligibleKindDescription(ineligibleParsed.kind)
                                        : observation.error_reason}
                                </p>
                            </LabeledRow>
                            {ineligibleParsed && ineligibleMessage && (
                                <LabeledRow label="Details">
                                    <p className="text-sm text-default m-0 leading-snug">{ineligibleMessage}</p>
                                </LabeledRow>
                            )}
                        </div>
                    )}

                    {observation.status === 'succeeded' && snapshot && result && (
                        <div className="flex flex-col gap-3">
                            {scannerType && (
                                <LabeledRow label="Type">
                                    <ScannerTypeBadge scannerType={scannerType} />
                                </LabeledRow>
                            )}
                            {prompt && scannerType !== 'summarizer' && (
                                <LabeledRow label="Prompt">
                                    <p className="text-sm text-default m-0 leading-snug">{prompt}</p>
                                </LabeledRow>
                            )}
                            <LabeledRow label={scannerType ? SUCCEEDED_OUTPUT_LABEL[scannerType] : ''}>
                                <ObservationPrimaryOutput
                                    observation={observation}
                                    showPrompt={false}
                                    onSeek={seekEmbeddedPlayer}
                                />
                            </LabeledRow>
                            {observation.completed_at && (
                                <LabeledRow label="Event">
                                    <Link to={urls.event(observation.id, observation.completed_at)}>
                                        $recording_observed
                                    </Link>
                                </LabeledRow>
                            )}
                            {qualityEnabled && (
                                <ObservationLabelControl
                                    observationId={observation.id}
                                    initialLabel={observation.label}
                                />
                            )}
                        </div>
                    )}

                    {(observation.status === 'pending' || observation.status === 'running') && (
                        <ObservationProgressBar observationId={observation.id} sessionId={observation.session_id} />
                    )}
                </section>

                {scannerType !== 'summarizer' && (
                    <section
                        className={`border rounded p-4 space-y-2 ${
                            reasoning ? 'bg-surface-primary' : 'bg-surface-secondary opacity-60'
                        }`}
                    >
                        <CardHeader icon={<IconThoughtBubble />} title="Model reasoning" />
                        {reasoning ? (
                            <p className="text-sm whitespace-pre-wrap m-0">
                                <CitedText text={reasoning} segments={reasoningSegments} onSeek={seekEmbeddedPlayer} />
                            </p>
                        ) : (
                            <p className="text-muted text-sm m-0 italic">
                                {observation.status === 'ineligible'
                                    ? 'The model was not invoked.'
                                    : observation.status === 'failed'
                                      ? 'No reasoning available — the observation failed before completion.'
                                      : observation.status === 'succeeded'
                                        ? 'No reasoning provided.'
                                        : 'Awaiting model output…'}
                            </p>
                        )}
                    </section>
                )}
            </div>

            <LemonCard className="overflow-hidden p-0" hoverEffect={false}>
                <div
                    className="flex items-center gap-2 bg-surface-primary p-3 cursor-pointer hover:bg-surface-secondary"
                    onClick={toggleRecordingExpanded}
                >
                    <LemonButton
                        icon={recordingExpanded ? <IconCollapse /> : <IconExpand />}
                        size="small"
                        tooltip={recordingExpanded ? 'Collapse recording' : 'Expand recording'}
                        onClick={(e) => {
                            e.stopPropagation()
                            toggleRecordingExpanded()
                        }}
                        data-attr="vision-observation-recording-toggle"
                    />
                    <IconVideoCamera className="text-muted-alt" />
                    <h3 className="text-lg font-semibold m-0">Recording</h3>
                </div>
                {recordingExpanded && (
                    <div className="border-t border-border h-[480px]">
                        <SessionRecordingPlayer
                            sessionRecordingId={observation.session_id}
                            playerKey={`vision-observation-${observation.id}`}
                            mode={SessionRecordingPlayerMode.Standard}
                            autoPlay={false}
                            noMeta
                            noBorder
                            withSidebar
                        />
                        {pendingSeek && (
                            <AutoSeekToTime
                                playerKey={`vision-observation-${observation.id}`}
                                sessionRecordingId={observation.session_id}
                                ms={pendingSeek.ms}
                                trigger={pendingSeek.trigger}
                            />
                        )}
                    </div>
                )}
            </LemonCard>
        </SceneContent>
    )
}

export default ReplayObservationSceneComponent
