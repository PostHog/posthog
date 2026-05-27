import { useValues } from 'kea'

import { LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import {
    CitedText,
    FailureDetail,
    IneligibleDetail,
    ObservationConfidence,
    ObservationPrimaryOutput,
    ObservationStatusTag,
    readConfig,
    readResult,
} from '../components/ObservationCard'
import { modelLabel, scannerTypeLabel } from '../replay_scanners/types'
import { replayObservationLogic } from './replayObservationLogic'
import { ReplayObservationSceneLogicProps, replayObservationSceneLogic } from './replayObservationSceneLogic'

export const scene: SceneExport<ReplayObservationSceneLogicProps> = {
    component: ReplayObservationSceneComponent,
    logic: replayObservationSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ReplayObservationSceneComponent({ tabId }: { tabId: string }): JSX.Element {
    const { observationId } = useValues(replayObservationSceneLogic)

    const observationLogic = replayObservationLogic({ id: observationId, tabId })
    useAttachedLogic(observationLogic, replayObservationSceneLogic)

    const { observation, observationLoading } = useValues(observationLogic)

    if (observationLoading) {
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
    const scannerType = snapshot?.scanner_type
    const scannerName = snapshot?.name || 'Scanner'
    const triggerLabel = observation.triggered_by === 'on_demand' ? 'On demand' : 'Schedule'
    const snapshotConfig = readConfig(snapshot ?? null)
    const prompt = typeof snapshotConfig.prompt === 'string' ? snapshotConfig.prompt : null
    const configuredTags =
        scannerType === 'classifier' && Array.isArray(snapshotConfig.tags)
            ? (snapshotConfig.tags as unknown[]).filter((t): t is string => typeof t === 'string')
            : []
    const multiLabel = scannerType === 'classifier' ? snapshotConfig.multi_label === true : false
    const summarizerLength =
        scannerType === 'summarizer' && typeof snapshotConfig.length === 'string' ? snapshotConfig.length : null
    const durationMs =
        observation.started_at && observation.completed_at
            ? dayjs(observation.completed_at).diff(observation.started_at)
            : null
    const durationLabel =
        durationMs !== null && Number.isFinite(durationMs) && durationMs >= 0
            ? durationMs < 1000
                ? `${durationMs} ms`
                : durationMs < 60_000
                  ? `${(durationMs / 1000).toFixed(1)} s`
                  : `${Math.floor(durationMs / 60_000)}m ${Math.floor((durationMs % 60_000) / 1000)}s`
            : null

    return (
        <SceneContent>
            <SceneTitleSection
                name={scannerName}
                description={`Observation on session ${observation.session_id}`}
                resourceType={{ type: 'replay_vision' }}
            />

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <section className="border rounded p-4 bg-surface-primary space-y-3">
                    <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-medium uppercase tracking-wide text-muted">Result</span>
                            {scannerType && <LemonTag type="option">{scannerTypeLabel(scannerType)}</LemonTag>}
                        </div>
                        <ObservationStatusTag status={observation.status} />
                    </div>

                    {observation.status === 'failed' && observation.error_reason && (
                        <FailureDetail errorReason={observation.error_reason} />
                    )}

                    {observation.status === 'ineligible' && observation.error_reason && (
                        <IneligibleDetail errorReason={observation.error_reason} />
                    )}

                    {observation.status === 'succeeded' && snapshot && result && (
                        <div className="flex flex-col gap-2">
                            {prompt && scannerType !== 'summarizer' && (
                                <p className="text-sm text-default m-0 leading-snug">{prompt}</p>
                            )}
                            <ObservationPrimaryOutput observation={observation} showPrompt={false} />
                            {configuredTags.length > 0 && (
                                <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
                                    <span>Allowed tags{multiLabel ? ' (multi-label)' : ''}:</span>
                                    {configuredTags.map((tag) => (
                                        <LemonTag key={tag} type="option" size="small">
                                            {tag}
                                        </LemonTag>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {(observation.status === 'pending' || observation.status === 'running') && (
                        <div className="text-muted text-sm">
                            {observation.status === 'pending' ? 'Queued…' : 'Analyzing recording…'}
                        </div>
                    )}
                </section>

                <section className="border rounded p-4 bg-surface-primary space-y-2">
                    <div className="text-sm font-medium">Reasoning</div>
                    {reasoning ? (
                        <p className="text-sm whitespace-pre-wrap m-0">
                            <CitedText observation={observation} text={reasoning} />
                        </p>
                    ) : (
                        <p className="text-muted text-sm m-0">No reasoning provided.</p>
                    )}
                </section>
            </div>

            <section className="border rounded p-4 bg-surface-primary">
                <div className="text-sm font-medium mb-3">Run details</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3 text-sm">
                    <div>
                        <div className="text-xs text-muted mb-0.5">Triggered by</div>
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
                    </div>
                    <div>
                        <div className="text-xs text-muted mb-0.5">Run at</div>
                        <TZLabel time={observation.created_at} />
                    </div>
                    {durationLabel && (
                        <div>
                            <div className="text-xs text-muted mb-0.5">Duration</div>
                            <span>{durationLabel}</span>
                        </div>
                    )}
                    {result && typeof result.confidence === 'number' && (
                        <div>
                            <div className="text-xs text-muted mb-0.5">Confidence</div>
                            <ObservationConfidence result={result} />
                        </div>
                    )}
                    {snapshot?.model && (
                        <div>
                            <div className="text-xs text-muted mb-0.5">Model</div>
                            <span>{modelLabel(snapshot.model)}</span>
                        </div>
                    )}
                    {typeof snapshot?.scanner_version === 'number' && (
                        <div>
                            <div className="text-xs text-muted mb-0.5">Scanner version</div>
                            <span>v{snapshot.scanner_version}</span>
                        </div>
                    )}
                    {summarizerLength && (
                        <div>
                            <div className="text-xs text-muted mb-0.5">Summary length</div>
                            <span className="capitalize">{summarizerLength}</span>
                        </div>
                    )}
                    {snapshot?.emits_signals && (
                        <div>
                            <div className="text-xs text-muted mb-0.5">Signals</div>
                            <span>Emitted ({observation.scanner_result?.signals_count ?? 0})</span>
                        </div>
                    )}
                </div>
            </section>

            <section className="border rounded bg-surface-primary overflow-hidden">
                <div className="p-4 pb-2 text-sm font-medium">Recording</div>
                <div className="aspect-video max-h-[80vh] min-h-[480px]">
                    <SessionRecordingPlayer
                        sessionRecordingId={observation.session_id}
                        playerKey={`vision-observation-${observation.id}`}
                        mode={SessionRecordingPlayerMode.Standard}
                        autoPlay={false}
                        noMeta
                        noBorder
                        withSidebar={false}
                    />
                </div>
            </section>
        </SceneContent>
    )
}

export default ReplayObservationSceneComponent
