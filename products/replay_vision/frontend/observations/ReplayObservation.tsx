import { useValues } from 'kea'

import { LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelInfoSection, ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ProductKey } from '~/queries/schema/schema-general'

import {
    CitedText,
    ObservationConfidence,
    ObservationPrimaryOutput,
    ObservationStatusTag,
} from '../components/ObservationCard'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { modelLabel, scannerTypeLabel } from '../replay_scanners/types'
import { replayObservationLogic } from './replayObservationLogic'
import { ReplayObservationSceneLogicProps, replayObservationSceneLogic } from './replayObservationSceneLogic'

export const scene: SceneExport<ReplayObservationSceneLogicProps> = {
    component: ReplayObservationSceneComponent,
    logic: replayObservationSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

function readResult(observation: ReplayObservationApi): Record<string, unknown> | null {
    const output = observation.scanner_result?.model_output
    return output && typeof output === 'object' ? (output as Record<string, unknown>) : null
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
    const triggerLabel =
        observation.triggered_by === 'on_demand'
            ? observation.triggered_by_user
                ? `On demand · ${observation.triggered_by_user.first_name || observation.triggered_by_user.email}`
                : 'On demand'
            : 'Schedule'
    const snapshotConfig =
        snapshot?.scanner_config && typeof snapshot.scanner_config === 'object'
            ? (snapshot.scanner_config as Record<string, unknown>)
            : {}
    const prompt = typeof snapshotConfig.prompt === 'string' ? snapshotConfig.prompt : null

    return (
        <SceneContent>
            <SceneTitleSection
                name={scannerName}
                description={`Observation on session ${observation.session_id}`}
                resourceType={{ type: 'replay_vision' }}
            />

            <ScenePanel>
                <ScenePanelInfoSection>
                    <ScenePanelLabel title="Scanner">
                        <Link to={urls.replayVision(observation.scanner_id)} className="text-sm">
                            {snapshot?.name || 'Scanner'}
                        </Link>
                    </ScenePanelLabel>
                    <ScenePanelLabel title="Session">
                        <Link to={urls.replaySingle(observation.session_id)} className="font-mono text-xs">
                            {observation.session_id}
                        </Link>
                    </ScenePanelLabel>
                    <ScenePanelLabel title="Triggered by">
                        <span className="text-sm">{triggerLabel}</span>
                    </ScenePanelLabel>
                    <ScenePanelLabel title="Run at">
                        <TZLabel time={observation.created_at} />
                    </ScenePanelLabel>
                    {observation.started_at && (
                        <ScenePanelLabel title="Started at">
                            <TZLabel time={observation.started_at} />
                        </ScenePanelLabel>
                    )}
                    {observation.completed_at && (
                        <ScenePanelLabel title="Completed at">
                            <TZLabel time={observation.completed_at} />
                        </ScenePanelLabel>
                    )}
                    {snapshot?.model && (
                        <ScenePanelLabel title="Model">
                            <span className="text-sm">{modelLabel(snapshot.model)}</span>
                        </ScenePanelLabel>
                    )}
                    {snapshot?.provider && (
                        <ScenePanelLabel title="Provider">
                            <span className="text-sm">{snapshot.provider}</span>
                        </ScenePanelLabel>
                    )}
                    {typeof snapshot?.scanner_version === 'number' && (
                        <ScenePanelLabel title="Scanner version">
                            <span className="text-sm">v{snapshot.scanner_version}</span>
                        </ScenePanelLabel>
                    )}
                    {snapshot?.emits_signals && (
                        <ScenePanelLabel title="Signals">
                            <span className="text-sm">Emitted ({observation.scanner_result?.signals_count ?? 0})</span>
                        </ScenePanelLabel>
                    )}
                </ScenePanelInfoSection>
            </ScenePanel>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <section className="border rounded p-4 bg-surface-primary space-y-3 lg:col-span-1">
                    <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-medium uppercase tracking-wide text-muted">Result</span>
                            {scannerType && <LemonTag type="option">{scannerTypeLabel(scannerType)}</LemonTag>}
                        </div>
                        <div className="flex items-center gap-2">
                            {result && typeof result.confidence === 'number' && (
                                <ObservationConfidence result={result} />
                            )}
                            <ObservationStatusTag status={observation.status} />
                        </div>
                    </div>

                    {observation.status === 'failed' && (
                        <div className="text-danger text-sm">{observation.error_reason || 'Unknown error'}</div>
                    )}

                    {observation.status === 'succeeded' && snapshot && result && (
                        <div className="flex flex-col gap-2">
                            {prompt && scannerType !== 'summarizer' && (
                                <p className="text-sm text-default m-0 leading-snug">{prompt}</p>
                            )}
                            <ObservationPrimaryOutput observation={observation} showPrompt={false} />
                        </div>
                    )}

                    {(observation.status === 'pending' || observation.status === 'running') && (
                        <div className="text-muted text-sm">
                            {observation.status === 'pending' ? 'Queued…' : 'Analyzing recording…'}
                        </div>
                    )}
                </section>

                <section className="border rounded p-4 bg-surface-primary space-y-2 lg:col-span-2">
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
