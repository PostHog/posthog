import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { reusableWidgetsDemoFrame } from 'products/notebooks/frontend/generated/api'

import { NotebookWidgetTrustControls } from '../NotebookNodeGeneratedWidget/NotebookWidgetTrustControls'
import {
    getNotebookWidgetTrust,
    notebookWidgetTrustLogic,
} from '../NotebookNodeGeneratedWidget/notebookWidgetTrustLogic'
import { WidgetArtifactFrame } from '../NotebookNodeGeneratedWidget/WidgetArtifactFrame'
import { ReusableWidgetLogicProps, reusableWidgetLogic } from './reusableWidgetLogic'
import { ReusableWidgetSourceModal } from './ReusableWidgetSourceModal'

export const scene: SceneExport<ReusableWidgetLogicProps> = {
    component: ReusableWidgetScene,
    logic: reusableWidgetLogic,
    paramsToProps: ({ params: { widgetId } }) => ({ widgetId: widgetId ?? '' }),
}

export function ReusableWidgetScene({ widgetId }: ReusableWidgetLogicProps): JSX.Element {
    const logic = reusableWidgetLogic({ widgetId })
    const trustLogic = useMountedLogic(notebookWidgetTrustLogic)
    const {
        artifactUnavailable,
        changePrompt,
        reusableWidget,
        reusableWidgetError,
        reusableWidgetLoading,
        runtimeError,
        updateError,
        updateInFlight,
    } = useValues(logic)
    const {
        loadReusableWidget,
        markArtifactUnavailable,
        openSourceModal,
        setChangePrompt,
        setRuntimeError,
        updateReusableWidget,
    } = useActions(logic)
    const { sessionBuildHashes, trustByUser } = useValues(trustLogic)
    const { trustBuild } = useActions(trustLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)

    if (reusableWidgetLoading && !reusableWidget) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-8 w-1/3" />
                <LemonSkeleton className="h-[32rem] w-full" />
            </SceneContent>
        )
    }
    if (!reusableWidget) {
        return reusableWidgetError ? <NotFound object="reusable widget" /> : <></>
    }

    const version = reusableWidget.current_version
    const trust = getNotebookWidgetTrust({
        trustByUser,
        sessionBuildHashes,
        userId: user?.id ?? null,
        buildHash: version.build_hash,
    })
    const trustControls = (variant: 'gate' | 'toolbar'): JSX.Element => (
        <NotebookWidgetTrustControls
            buildHash={version.build_hash}
            isEditable={false}
            securityReview={version.security_review}
            variant={variant}
            onRun={() => {
                if (version.build_hash) {
                    trustBuild(user?.id ?? null, version.build_hash)
                }
            }}
            onViewSource={openSourceModal}
        />
    )

    return (
        <SceneContent className="flex-1 min-h-0">
            <SceneTitleSection
                name={reusableWidget.name}
                description={reusableWidget.description || 'Reusable notebook widget'}
                resourceType={{ type: 'notebook' }}
                actions={<LemonButton onClick={openSourceModal}>View source</LemonButton>}
            />
            {reusableWidget.tags.length ? (
                <div className="flex flex-wrap gap-1">
                    {reusableWidget.tags.map((tag) => (
                        <LemonTag key={tag}>{tag}</LemonTag>
                    ))}
                </div>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded border bg-surface-primary p-3">
                    <div className="text-xs text-secondary">Current version</div>
                    <div className="font-semibold">Version {reusableWidget.version_count}</div>
                </div>
                <div className="rounded border bg-surface-primary p-3">
                    <div className="text-xs text-secondary">Notebook placements</div>
                    <div className="font-semibold">{reusableWidget.instance_count}</div>
                </div>
            </div>
            <div className="rounded border bg-surface-primary p-3">
                <div className="mb-2 font-semibold">Input contract</div>
                {version.input_contract.length ? (
                    <div className="flex flex-col gap-2">
                        {version.input_contract.map((input) => (
                            <div key={input.slot} className="rounded border p-2">
                                <div className="font-medium">{input.slot}</div>
                                <div className="mt-1 flex flex-wrap gap-1">
                                    {(input.columns ?? []).map((column) => (
                                        <LemonTag key={column.name} size="small">
                                            {column.name}: {column.type}
                                        </LemonTag>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="text-sm text-secondary">This widget does not require notebook data.</div>
                )}
            </div>
            <div className="rounded border bg-surface-primary p-3">
                <div className="mb-1 font-semibold">Update this reusable widget</div>
                <div className="mb-3 text-sm text-secondary">
                    Describe a focused change. A new immutable version will become the default for every unpinned
                    notebook instance.
                </div>
                <div className="flex flex-col gap-2">
                    <LemonTextArea
                        value={changePrompt}
                        onChange={setChangePrompt}
                        onPressCmdEnter={() => updateReusableWidget('improve')}
                        placeholder="Describe the change you want."
                        minRows={3}
                        className="ph-no-capture"
                    />
                    <div className="flex justify-end">
                        <LemonButton
                            onClick={() => updateReusableWidget('regenerate')}
                            loading={updateInFlight}
                            disabledReason={!changePrompt.trim() ? 'Describe the new widget you want.' : undefined}
                        >
                            Regenerate
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => updateReusableWidget('improve')}
                            loading={updateInFlight}
                            disabledReason={!changePrompt.trim() ? 'Describe the change you want.' : undefined}
                        >
                            Improve
                        </LemonButton>
                    </div>
                    {updateError ? <LemonBanner type="error">{updateError}</LemonBanner> : null}
                </div>
            </div>
            <div className="flex min-h-[32rem] flex-1 flex-col overflow-hidden rounded border bg-primary">
                {reusableWidgetError ? (
                    <LemonBanner type="warning" action={{ children: 'Retry', onClick: loadReusableWidget }}>
                        The widget couldn't be refreshed. The last loaded version is shown.
                    </LemonBanner>
                ) : null}
                {runtimeError ? (
                    <LemonBanner type="warning" onClose={() => setRuntimeError(null)}>
                        {runtimeError}
                    </LemonBanner>
                ) : null}
                {!version.artifact_url || artifactUnavailable ? (
                    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
                        <span>This widget's demo preview is unavailable.</span>
                        <LemonButton onClick={openSourceModal}>View source</LemonButton>
                    </div>
                ) : !trust.buildTrusted ? (
                    trustControls('gate')
                ) : (
                    <>
                        {trustControls('toolbar')}
                        <div className="min-h-0 flex-1">
                            <WidgetArtifactFrame
                                artifactUrl={version.artifact_url}
                                title={`${reusableWidget.name} demo`}
                                allowedFrames={version.frame_names}
                                onReadFrame={async (name, _offset, _limit, _runId, signal) => {
                                    if (!currentTeamId) {
                                        throw new Error('Select a project to load demo data.')
                                    }
                                    return await reusableWidgetsDemoFrame(
                                        String(currentTeamId),
                                        reusableWidget.id,
                                        name,
                                        { signal }
                                    )
                                }}
                                onArtifactUnavailable={markArtifactUnavailable}
                                onError={(message) =>
                                    setRuntimeError(message || "The widget couldn't load its saved demo data.")
                                }
                            />
                        </div>
                    </>
                )}
            </div>
            <ReusableWidgetSourceModal widgetId={widgetId} />
        </SceneContent>
    )
}
