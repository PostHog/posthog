import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

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
        reviewError,
        reviewResultLoading,
        runtimeError,
        updateError,
        updateInFlight,
    } = useValues(logic)
    const {
        loadReusableWidget,
        markArtifactUnavailable,
        openSourceModal,
        discardVersion,
        saveVersion,
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

    const pendingVersion = reusableWidget.pending_version
    const version = pendingVersion ?? reusableWidget.current_version
    const draftReady = pendingVersion?.build_status === 'ready' && !!pendingVersion.artifact_url
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
            <div className={`grid gap-3 ${pendingVersion ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
                <div className="rounded border bg-surface-primary p-3">
                    <div className="text-xs text-secondary">Published version</div>
                    <div className="font-semibold">Version {reusableWidget.version_count}</div>
                </div>
                {pendingVersion ? (
                    <div className="rounded border bg-surface-primary p-3">
                        <div className="text-xs text-secondary">Draft awaiting review</div>
                        <div className="font-semibold">Version {pendingVersion.version}</div>
                    </div>
                ) : null}
                <div className="rounded border bg-surface-primary p-3">
                    <div className="text-xs text-secondary">Notebook placements</div>
                    <div className="font-semibold">{reusableWidget.instance_count}</div>
                </div>
            </div>
            <div className="rounded border bg-surface-primary p-3">
                <div className="mb-2 font-semibold">{pendingVersion ? 'Draft input contract' : 'Input contract'}</div>
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
            {pendingVersion ? (
                <div className="rounded border bg-surface-primary p-3">
                    <div className="mb-1 font-semibold">Review draft version {pendingVersion.version}</div>
                    <div className="mb-3 text-sm text-secondary">
                        Check the preview, input contract, and source. The published version remains the default for
                        every unpinned notebook until you save this draft.
                    </div>
                    {!draftReady ? (
                        <LemonBanner type={pendingVersion.build_status === 'failed' ? 'error' : 'info'}>
                            {pendingVersion.build_status === 'failed'
                                ? 'The draft preview could not be built. Discard it and try another update.'
                                : 'The draft preview is still building. You can save it after it is ready to review.'}
                        </LemonBanner>
                    ) : null}
                    <div className="mt-3 flex justify-end gap-2">
                        <LemonButton
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Discard this draft?',
                                    description:
                                        'The published version will stay unchanged. You can generate another draft afterward.',
                                    primaryButton: {
                                        children: 'Discard draft',
                                        status: 'danger',
                                        onClick: discardVersion,
                                    },
                                    secondaryButton: { children: 'Keep reviewing' },
                                })
                            }
                            loading={reviewResultLoading}
                            data-attr="reusable-widget-discard-draft"
                        >
                            Discard draft
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={saveVersion}
                            loading={reviewResultLoading}
                            disabledReason={!draftReady ? 'Wait for the draft preview to finish building.' : undefined}
                            data-attr="reusable-widget-save-version"
                        >
                            Save version
                        </LemonButton>
                    </div>
                    {reviewError ? <LemonBanner type="error">{reviewError}</LemonBanner> : null}
                </div>
            ) : (
                <div className="rounded border bg-surface-primary p-3">
                    <div className="mb-1 font-semibold">Update this reusable widget</div>
                    <div className="mb-3 text-sm text-secondary">
                        Describe a focused change. We'll generate a draft for you to review before it changes any
                        unpinned notebook instance.
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
                        <div className="flex justify-end gap-2">
                            <LemonButton
                                onClick={() => updateReusableWidget('regenerate')}
                                loading={updateInFlight}
                                disabledReason={!changePrompt.trim() ? 'Describe the new widget you want.' : undefined}
                                data-attr="reusable-widget-regenerate-draft"
                            >
                                Regenerate
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => updateReusableWidget('improve')}
                                loading={updateInFlight}
                                disabledReason={!changePrompt.trim() ? 'Describe the change you want.' : undefined}
                                data-attr="reusable-widget-improve-draft"
                            >
                                Improve
                            </LemonButton>
                        </div>
                        {updateError ? <LemonBanner type="error">{updateError}</LemonBanner> : null}
                    </div>
                </div>
            )}
            <div className="flex min-h-[32rem] flex-1 flex-col overflow-hidden rounded border bg-primary">
                <div className="border-b px-3 py-2">
                    <div className="font-semibold">{pendingVersion ? 'Draft preview' : 'Published preview'}</div>
                    {pendingVersion ? (
                        <div className="text-xs text-secondary">
                            Saving this draft will publish version {version.version}.
                        </div>
                    ) : null}
                </div>
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
                        <span>
                            {pendingVersion && pendingVersion.build_status !== 'failed'
                                ? 'The draft preview is still building.'
                                : "This widget's demo preview is unavailable."}
                        </span>
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
                                        { version_id: version.id },
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
