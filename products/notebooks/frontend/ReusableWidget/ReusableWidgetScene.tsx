import { useActions, useMountedLogic, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonLabel,
    LemonSelect,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
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
import { WIDGET_MODEL_OPTIONS } from '../NotebookNodeGeneratedWidget/widgetModels'
import { ReusableWidgetDemoDataModal } from './ReusableWidgetDemoDataModal'
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
        demoDataModalOpen,
        demoDataRevision,
        reusableWidget,
        reusableWidgetError,
        reusableWidgetLoading,
        reviewError,
        reviewResultLoading,
        runtimeError,
        selectedVersion,
        versionHistory,
        versionHistoryLoading,
        versionHistoryError,
        updateError,
        updateInFlight,
        updateModel,
        updateOperation,
    } = useValues(logic)
    const {
        loadReusableWidget,
        markArtifactUnavailable,
        openSourceModal,
        openDemoDataModal,
        closeDemoDataModal,
        demoDataSaved,
        discardVersion,
        saveVersion,
        restoreVersion,
        selectVersion,
        loadVersionHistory,
        setChangePrompt,
        setRuntimeError,
        setUpdateModel,
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
    if (!reusableWidget || !selectedVersion) {
        return reusableWidgetError ? <NotFound object="reusable widget" /> : <></>
    }

    const pendingVersion = reusableWidget.pending_version
    const version = selectedVersion
    const isDraft = version.id === pendingVersion?.id
    const isHistorical = !isDraft && version.id !== reusableWidget.current_version.id
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
        <SceneContent className="@container/reusable-widget flex-1 min-h-0">
            <SceneTitleSection
                name={reusableWidget.name}
                description={reusableWidget.description || 'Reusable notebook widget'}
                resourceType={{ type: 'notebook' }}
                forceBackTo={{
                    key: 'reusable-widgets',
                    name: 'Reusable widgets',
                    path: `${urls.notebooks()}?tab=widgets`,
                }}
                actions={
                    <div className="flex flex-wrap gap-2">
                        <LemonButton onClick={openDemoDataModal} data-attr="reusable-widget-demo-data">
                            Demo data
                        </LemonButton>
                        <LemonButton onClick={openSourceModal}>View source</LemonButton>
                    </div>
                }
            />
            <div className="grid grid-cols-1 items-start gap-4 @min-[56rem]/reusable-widget:grid-cols-3">
                <div className="flex min-w-0 flex-col gap-4">
                    {reusableWidget.tags.length ? (
                        <div className="flex flex-wrap gap-1">
                            {reusableWidget.tags.map((tag) => (
                                <LemonTag key={tag}>{tag}</LemonTag>
                            ))}
                        </div>
                    ) : null}
                    <div className="grid grid-cols-2 gap-3">
                        <div className="rounded border bg-surface-primary p-3">
                            <div className="text-xs text-secondary">Published version</div>
                            <div className="font-semibold">Version {reusableWidget.version_count}</div>
                        </div>
                        <div className="rounded border bg-surface-primary p-3">
                            <div className="text-xs text-secondary">Uses in notebooks</div>
                            <div className="font-semibold">{reusableWidget.instance_count}</div>
                        </div>
                    </div>
                    <div className="rounded border bg-surface-primary p-3">
                        <div className="mb-2 font-semibold">{isDraft ? 'Draft input contract' : 'Input contract'}</div>
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
                    {isDraft && pendingVersion ? (
                        <div className="rounded border bg-surface-primary p-3">
                            <div className="mb-1 font-semibold">Review draft version {pendingVersion.version}</div>
                            <div className="mb-3 text-sm text-secondary">
                                Check the preview, input contract, and source. The published version remains the default
                                for every unpinned notebook until you save this draft.
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
                                    disabledReason={
                                        !draftReady ? 'Wait for the draft preview to finish building.' : undefined
                                    }
                                    data-attr="reusable-widget-save-version"
                                >
                                    Save version
                                </LemonButton>
                            </div>
                            {reviewError ? <LemonBanner type="error">{reviewError}</LemonBanner> : null}
                        </div>
                    ) : isHistorical ? (
                        <div className="rounded border bg-surface-primary p-3">
                            <div className="mb-1 font-semibold">Restore version {version.version}</div>
                            <div className="mb-3 text-sm text-secondary">
                                Make this version the latest to use it in every unpinned notebook. This creates a new
                                version and keeps the existing history and pins.
                            </div>
                            <LemonButton
                                type="primary"
                                loading={reviewResultLoading}
                                disabledReason={
                                    pendingVersion || updateInFlight
                                        ? 'Finish or discard the current update first.'
                                        : !version.artifact_url || version.build_status !== 'ready'
                                          ? 'This version has no ready preview.'
                                          : undefined
                                }
                                onClick={() =>
                                    LemonDialog.open({
                                        title: `Make version ${version.version} the latest?`,
                                        description: `This creates version ${reusableWidget.version_count + 1} and updates every unpinned notebook using this widget. Pinned notebooks keep their selected version.`,
                                        primaryButton: { children: 'Make latest', onClick: restoreVersion },
                                        secondaryButton: { children: 'Cancel' },
                                    })
                                }
                            >
                                Make latest
                            </LemonButton>
                            {reviewError ? (
                                <LemonBanner type="error" className="mt-2">
                                    {reviewError}
                                </LemonBanner>
                            ) : null}
                        </div>
                    ) : pendingVersion ? (
                        <LemonBanner
                            type="info"
                            action={{ children: 'Review draft', onClick: () => selectVersion(pendingVersion.id) }}
                        >
                            A draft is awaiting review.
                        </LemonBanner>
                    ) : (
                        <div className="rounded border bg-surface-primary p-3">
                            <div className="mb-1 font-semibold">Update this reusable widget</div>
                            <div className="mb-3 text-sm text-secondary">
                                Describe a focused change. We'll generate a draft for you to review before it changes
                                any unpinned notebook instance.
                            </div>
                            <div className="flex flex-col gap-2">
                                <LemonTextArea
                                    value={changePrompt}
                                    onChange={setChangePrompt}
                                    onPressCmdEnter={() => updateReusableWidget('improve')}
                                    placeholder="Describe the change you want."
                                    minRows={3}
                                    className="ph-no-capture"
                                    disabled={updateInFlight}
                                />
                                <div>
                                    <LemonLabel htmlFor={`reusable-widget-model-${widgetId}`}>Model</LemonLabel>
                                    <LemonSelect
                                        id={`reusable-widget-model-${widgetId}`}
                                        value={updateModel}
                                        options={WIDGET_MODEL_OPTIONS}
                                        onChange={setUpdateModel}
                                        disabled={updateInFlight}
                                        fullWidth
                                        className="mt-1"
                                        data-attr="reusable-widget-model"
                                    />
                                </div>
                                <div className="flex flex-wrap items-center gap-2">
                                    <LemonButton
                                        type="primary"
                                        onClick={() => updateReusableWidget('improve')}
                                        loading={updateOperation === 'improve'}
                                        disabledReason={
                                            updateInFlight
                                                ? 'Wait for the current update to finish.'
                                                : !changePrompt.trim()
                                                  ? 'Describe the change you want.'
                                                  : undefined
                                        }
                                        data-attr="reusable-widget-improve-draft"
                                    >
                                        Improve
                                    </LemonButton>
                                    <LemonButton
                                        onClick={() => updateReusableWidget('regenerate')}
                                        loading={updateOperation === 'regenerate'}
                                        disabledReason={
                                            updateInFlight
                                                ? 'Wait for the current update to finish.'
                                                : !changePrompt.trim()
                                                  ? 'Describe the new widget you want.'
                                                  : undefined
                                        }
                                        data-attr="reusable-widget-regenerate-draft"
                                    >
                                        Regenerate
                                    </LemonButton>
                                </div>
                                {updateError ? <LemonBanner type="error">{updateError}</LemonBanner> : null}
                            </div>
                        </div>
                    )}
                </div>
                <div
                    className="flex min-h-96 min-w-0 resize-y flex-col overflow-hidden rounded border bg-primary @min-[56rem]/reusable-widget:col-span-2"
                    style={{ height: 640 }}
                    data-attr="reusable-widget-preview"
                >
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
                        <div className="font-semibold">
                            {isDraft ? 'Draft preview' : isHistorical ? 'Version preview' : 'Published preview'}
                        </div>
                        <LemonSelect
                            aria-label="Widget version"
                            value={version.id}
                            loading={versionHistoryLoading}
                            disabled={reviewResultLoading}
                            options={[
                                ...(pendingVersion
                                    ? [{ value: pendingVersion.id, label: `Version ${pendingVersion.version} · Draft` }]
                                    : []),
                                {
                                    value: reusableWidget.current_version.id,
                                    label: `Version ${reusableWidget.current_version.version} · Latest`,
                                },
                                ...(versionHistory?.results ?? [])
                                    .filter(
                                        (item) =>
                                            item.id !== reusableWidget.current_version.id &&
                                            item.id !== pendingVersion?.id
                                    )
                                    .map((item) => ({ value: item.id, label: `Version ${item.version}` })),
                                ...(versionHistory?.next_offset != null
                                    ? [{ value: 'load-more', label: 'Load older versions' }]
                                    : []),
                            ]}
                            onChange={(id) => {
                                if (id === 'load-more') {
                                    loadVersionHistory(versionHistory?.next_offset ?? 0)
                                } else {
                                    selectVersion(id)
                                }
                            }}
                            data-attr="reusable-widget-version"
                        />
                    </div>
                    {versionHistoryError ? (
                        <LemonBanner type="warning" action={{ children: 'Retry', onClick: () => loadVersionHistory() }}>
                            Version history couldn't be loaded.
                        </LemonBanner>
                    ) : null}
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
                                {version.build_status === 'queued' || version.build_status === 'building'
                                    ? 'The preview is still building.'
                                    : "This widget's demo preview is unavailable."}
                            </span>
                            <LemonButton onClick={openSourceModal}>View source</LemonButton>
                        </div>
                    ) : !trust.buildTrusted &&
                      (version.security_review?.severity !== 'none' || version.frame_names.length > 0) ? (
                        trustControls('gate')
                    ) : (
                        <>
                            {trustControls('toolbar')}
                            <div className="min-h-0 flex-1">
                                <WidgetArtifactFrame
                                    key={`${version.id}:${demoDataRevision}`}
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
                    <div className="shrink-0 border-t px-3 py-1 text-xs text-muted">
                        Drag the bottom-right corner to resize the preview.
                    </div>
                </div>
            </div>
            <ReusableWidgetSourceModal widgetId={widgetId} />
            {demoDataModalOpen && currentTeamId ? (
                <ReusableWidgetDemoDataModal
                    projectId={currentTeamId}
                    widgetId={widgetId}
                    version={version}
                    canEdit={!isHistorical}
                    onClose={closeDemoDataModal}
                    onSaved={demoDataSaved}
                />
            ) : null}
        </SceneContent>
    )
}
