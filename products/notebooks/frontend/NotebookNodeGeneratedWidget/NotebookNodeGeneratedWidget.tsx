import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { useComponentPanelState } from 'lib/components/MarkdownNotebook/componentPanelContext'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { UnsupportedNodePlaceholder } from 'scenes/notebooks/Nodes/sharedNodeSupport'
import { NotebookNodeAttributes, NotebookNodeProps, NotebookNodeType } from 'scenes/notebooks/types'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    formatWidgetElapsed,
    loadWidgetFrame,
    notebookNodeGeneratedWidgetLogic,
} from './notebookNodeGeneratedWidgetLogic'
import { NotebookNodeGeneratedWidgetSettings } from './NotebookNodeGeneratedWidgetSettings'
import { NotebookWidgetGenerationModal } from './NotebookWidgetGenerationModal'
import { NotebookWidgetSourceModal } from './NotebookWidgetSourceModal'
import { NotebookWidgetTrustControls } from './NotebookWidgetTrustControls'
import { getNotebookWidgetTrust, notebookWidgetTrustLogic } from './notebookWidgetTrustLogic'
import { WidgetArtifactFrame } from './WidgetArtifactFrame'
import { DEFAULT_WIDGET_MODEL, isWidgetModel, type WidgetModel } from './widgetModels'

export type NotebookNodeGeneratedWidgetAttributes = {
    prompt?: string
    model?: WidgetModel
}

function EmptyState({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="flex h-full min-h-32 items-center justify-center p-4 text-center text-secondary">
            {children}
        </div>
    )
}

function Component({ attributes }: NotebookNodeProps<NotebookNodeGeneratedWidgetAttributes>): JSX.Element | null {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded, notebookLogic } = useValues(nodeLogic)
    const { isShared } = useValues(notebookLogic)

    if (!expanded) {
        return null
    }
    return isShared ? <UnsupportedNodePlaceholder /> : <ExpandedWidget attributes={attributes} />
}

function ExpandedWidget({
    attributes,
}: {
    attributes: NotebookNodeAttributes<NotebookNodeGeneratedWidgetAttributes>
}): JSX.Element | null {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const componentPanelState = useComponentPanelState()
    const { isEditable, notebookLogic } = useValues(nodeLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const notebookShortId = notebookLogic.props.shortId
    // Markdown props are cast without runtime validation, so a hand-written or legacy
    // tag can supply a non-string prompt or an unsupported model. Coerce both here, the
    // same way the run-button toolbar and the sibling code/height nodes do.
    const prompt = typeof attributes.prompt === 'string' ? attributes.prompt : ''
    const model = isWidgetModel(attributes.model) ? attributes.model : DEFAULT_WIDGET_MODEL
    const logicProps = {
        projectId: currentTeamId,
        notebookShortId,
        nodeId: attributes.nodeId,
        prompt,
        model,
        isEditable,
        persistNotebook: async (): Promise<void> => {
            await notebookLogic.asyncActions.saveNotebook({
                content: notebookLogic.values.content,
                title: notebookLogic.values.title,
            })
        },
        getContent: () => notebookLogic.values.content ?? null,
    }
    const logic = notebookNodeGeneratedWidgetLogic(logicProps)
    const trustLogic = useMountedLogic(notebookWidgetTrustLogic)
    const { sessionBuildHashes, trustByUser } = useValues(trustLogic)
    const {
        artifactUnavailable,
        artifactLoading,
        activeFrameNames,
        cancellationInFlight,
        dataRefreshInFlight,
        elapsedSeconds,
        frameRevision,
        generationError,
        generationRequestLoading,
        isWorking,
        runtimeError,
        runDataDependenciesDisabledReason,
        selectedVersion,
        selectedVersionId,
        status,
        statusLoadError,
        statusLoading,
        versionsError,
        versionsLoading,
        workingStatus,
    } = useValues(logic)
    const {
        artifactAvailable,
        artifactUnavailable: markArtifactUnavailable,
        cancelGeneration,
        clearGenerationError,
        generateWidget,
        loadStatus,
        loadVersions,
        openGenerationModal,
        openSourceModal,
        refreshData,
        runDataDependencies,
        setRuntimeError,
    } = useActions(logic)
    const { trustBuild } = useActions(trustLogic)

    if (statusLoading && !status) {
        return (
            <div className="flex h-full flex-col gap-3 p-3">
                <LemonSkeleton className="h-6 w-1/3" />
                <LemonSkeleton className="min-h-32 flex-1 w-full" />
            </div>
        )
    }
    if (statusLoadError && !status) {
        return (
            <EmptyState>
                <div className="flex flex-col items-center gap-3">
                    <div>We couldn't load this widget's status.</div>
                    <LemonButton onClick={loadStatus} loading={statusLoading}>
                        Retry
                    </LemonButton>
                </div>
            </EmptyState>
        )
    }

    const initialPrompt = prompt.trim()
    const selectedArtifactUrl =
        selectedVersionId === status?.current_version_id ? status?.artifact_url : selectedVersion?.artifact_url
    const selectedBuildHash =
        selectedVersionId === status?.current_version_id
            ? (status?.build_hash ?? null)
            : (selectedVersion?.build_hash ?? null)
    const selectedSecurityReview =
        selectedVersionId === status?.current_version_id
            ? (status?.security_review ?? null)
            : (selectedVersion?.security_review ?? null)
    const widgetTrust = getNotebookWidgetTrust({
        trustByUser,
        sessionBuildHashes,
        userId: user?.id ?? null,
        buildHash: selectedBuildHash,
    })
    const trustControls = (variant: 'gate' | 'toolbar'): JSX.Element => (
        <NotebookWidgetTrustControls
            buildHash={selectedBuildHash}
            isEditable={isEditable}
            securityReview={selectedSecurityReview}
            variant={variant}
            onRun={() => {
                if (selectedBuildHash) {
                    trustBuild(user?.id ?? null, selectedBuildHash)
                }
            }}
            onViewSource={openSourceModal}
        />
    )
    if (artifactUnavailable && selectedArtifactUrl) {
        return (
            <>
                <EmptyState>
                    <div className="flex flex-col items-center gap-3">
                        <div>This widget's preview didn't load.</div>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton onClick={refreshData} loading={dataRefreshInFlight}>
                                Reload preview
                            </LemonButton>
                            <LemonButton onClick={openSourceModal}>View source</LemonButton>
                        </div>
                    </div>
                </EmptyState>
                {!componentPanelState?.showEditPanel ? <NotebookWidgetSourceModal {...logicProps} /> : null}
            </>
        )
    }

    if (selectedArtifactUrl && selectedVersionId && currentTeamId) {
        if (!widgetTrust.buildTrusted) {
            return (
                <>
                    {trustControls('gate')}
                    {!componentPanelState?.showEditPanel ? <NotebookWidgetSourceModal {...logicProps} /> : null}
                </>
            )
        }
        return (
            <>
                <div className="flex h-full min-h-0 w-full flex-col">
                    {trustControls('toolbar')}
                    {isWorking && workingStatus && !componentPanelState?.showEditPanel ? (
                        <div className="flex flex-wrap items-center gap-2 border-b p-2 text-sm">
                            <span className="flex items-center gap-2" role="status" aria-live="polite">
                                <Spinner />
                                <span>{workingStatus.label}</span>
                            </span>
                            <span className="font-mono tabular-nums" aria-hidden="true">
                                {formatWidgetElapsed(elapsedSeconds)}
                            </span>
                            <span className="text-muted">{workingStatus.detail}</span>
                            {isEditable ? (
                                <LemonButton size="xsmall" onClick={cancelGeneration} loading={cancellationInFlight}>
                                    Cancel
                                </LemonButton>
                            ) : null}
                        </div>
                    ) : null}
                    {generationError ||
                    (!generationRequestLoading && status?.lifecycle_status === 'failed' && status.error_detail) ? (
                        <LemonBanner
                            type="error"
                            className="m-2"
                            onClose={generationError ? clearGenerationError : undefined}
                        >
                            {generationError || status?.error_detail}
                        </LemonBanner>
                    ) : null}
                    {statusLoadError ? (
                        <LemonBanner type="warning" className="m-2" action={{ children: 'Retry', onClick: loadStatus }}>
                            The widget status couldn't be refreshed. The preview below is the last confirmed version.
                        </LemonBanner>
                    ) : null}
                    {runtimeError ? (
                        <LemonBanner
                            type="warning"
                            className="m-2"
                            onClose={() => setRuntimeError(null)}
                            action={
                                isEditable
                                    ? {
                                          children: 'Run data cells',
                                          onClick: runDataDependencies,
                                          loading: dataRefreshInFlight,
                                          disabledReason: runDataDependenciesDisabledReason ?? undefined,
                                          'data-attr': 'notebook-widget-runtime-run-data',
                                      }
                                    : undefined
                            }
                        >
                            <span className="ph-no-capture">{runtimeError}</span>
                        </LemonBanner>
                    ) : null}
                    <div className="relative min-h-0 flex-1" aria-busy={artifactLoading}>
                        {artifactLoading ? (
                            <div
                                className="absolute inset-0 z-10 flex items-center justify-center gap-2 bg-primary text-secondary"
                                role="status"
                                aria-live="polite"
                            >
                                <Spinner />
                                Loading widget…
                            </div>
                        ) : null}
                        <WidgetArtifactFrame
                            key={`${selectedBuildHash}-${frameRevision}`}
                            artifactUrl={selectedArtifactUrl}
                            title="Widget"
                            allowedFrames={activeFrameNames}
                            onReadFrame={(name, offset, limit, runId, signal) =>
                                loadWidgetFrame(
                                    String(currentTeamId),
                                    notebookShortId,
                                    attributes.nodeId,
                                    selectedVersionId,
                                    name,
                                    offset,
                                    limit,
                                    runId,
                                    signal
                                )
                            }
                            onArtifactUnavailable={markArtifactUnavailable}
                            onError={(message) =>
                                setRuntimeError(
                                    message ||
                                        'The widget could not load its notebook data. Run its data cells and try again.'
                                )
                            }
                            onRendered={() => {
                                // A failed startup posts `error` before the load-driven `rendered`.
                                // Clearing the error here would hide that warning. The reducer already
                                // drops a stale error when a new document loads (refresh, generate, version switch).
                                artifactAvailable()
                            }}
                        />
                    </div>
                </div>
                {!componentPanelState?.showEditPanel ? <NotebookWidgetSourceModal {...logicProps} /> : null}
            </>
        )
    }

    if (isWorking) {
        if (componentPanelState?.showEditPanel) {
            return null
        }
        return (
            <EmptyState>
                <div className="flex max-w-lg flex-col items-center gap-3">
                    <div className="flex items-center gap-2">
                        <span className="flex items-center gap-2" role="status" aria-live="polite">
                            <Spinner />
                            <span>{workingStatus?.label}</span>
                        </span>
                        <span className="font-mono tabular-nums" aria-hidden="true">
                            {formatWidgetElapsed(elapsedSeconds)}
                        </span>
                    </div>
                    {workingStatus ? (
                        <div className="flex flex-col gap-1 text-sm">
                            <span>{workingStatus.detail}</span>
                            <span className={workingStatus.isOverEstimate ? 'text-warning' : 'text-muted'}>
                                {workingStatus.timing}
                            </span>
                        </div>
                    ) : null}
                    {generationError ? (
                        <LemonBanner type="error" onClose={clearGenerationError}>
                            {generationError}
                        </LemonBanner>
                    ) : null}
                    {statusLoadError ? (
                        <LemonBanner type="warning" action={{ children: 'Retry', onClick: loadStatus }}>
                            The widget status couldn't be refreshed. The last confirmed generation state is shown.
                        </LemonBanner>
                    ) : null}
                    {status?.active_job && isEditable ? (
                        <LemonButton onClick={cancelGeneration} loading={cancellationInFlight}>
                            Cancel
                        </LemonButton>
                    ) : null}
                </div>
            </EmptyState>
        )
    }

    if (generationRequestLoading) {
        return (
            <EmptyState>
                <div className="flex items-center gap-2" role="status" aria-live="polite">
                    <Spinner />
                    Starting widget generation…
                </div>
            </EmptyState>
        )
    }

    if (status?.lifecycle_status === 'failed' || generationError) {
        return (
            <>
                <EmptyState>
                    <div className="flex flex-col items-center gap-3">
                        <div>{status?.error_detail || generationError || 'The widget could not be generated.'}</div>
                        {isEditable ? (
                            status?.has_versions ? (
                                <LemonButton type="primary" onClick={() => openGenerationModal('regenerate')}>
                                    Regenerate…
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    type="primary"
                                    onClick={() => generateWidget(initialPrompt, model, 'initial')}
                                    loading={generationRequestLoading}
                                >
                                    Generate widget
                                </LemonButton>
                            )
                        ) : (
                            <div className="text-sm text-muted">
                                Ask an editor to {status?.has_versions ? 'regenerate' : 'generate'} this widget.
                            </div>
                        )}
                    </div>
                </EmptyState>
                {!componentPanelState?.showEditPanel ? <NotebookWidgetGenerationModal logicProps={logicProps} /> : null}
            </>
        )
    }

    if (status?.has_versions && versionsError && !versionsLoading && !selectedVersion) {
        return (
            <>
                <EmptyState>
                    <div className="flex flex-col items-center gap-3">
                        <div>We couldn't load this widget version.</div>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton onClick={() => loadVersions(true)}>Retry</LemonButton>
                            <LemonButton onClick={openSourceModal}>View source</LemonButton>
                        </div>
                    </div>
                </EmptyState>
                {!componentPanelState?.showEditPanel ? <NotebookWidgetSourceModal {...logicProps} /> : null}
            </>
        )
    }
    if (status?.has_versions && versionsLoading) {
        return (
            <EmptyState>
                <div className="flex items-center gap-2">
                    <Spinner />
                    Loading widget version…
                </div>
            </EmptyState>
        )
    }
    if (status?.has_versions) {
        return (
            <>
                <EmptyState>
                    <div className="flex flex-col items-center gap-3">
                        <div>
                            {isEditable
                                ? "This version's preview is no longer available. Its prompt and source remain in version history."
                                : "This version's preview is no longer available. Ask an editor to restore or regenerate it."}
                        </div>
                        <LemonButton onClick={openSourceModal}>View source</LemonButton>
                    </div>
                </EmptyState>
                {!componentPanelState?.showEditPanel ? <NotebookWidgetSourceModal {...logicProps} /> : null}
            </>
        )
    }
    return (
        <EmptyState>
            <div className="flex flex-col items-center gap-3">
                <div>This widget has not been generated yet.</div>
                {isEditable ? (
                    <LemonButton
                        type="primary"
                        onClick={() => generateWidget(initialPrompt, model, 'initial')}
                        loading={generationRequestLoading}
                    >
                        Generate widget
                    </LemonButton>
                ) : (
                    <div className="text-sm text-muted">Ask an editor to generate this widget.</div>
                )}
            </div>
        </EmptyState>
    )
}

export const NotebookNodeGeneratedWidget = createPostHogWidgetNode<NotebookNodeGeneratedWidgetAttributes>({
    nodeType: NotebookNodeType.GeneratedWidget,
    titlePlaceholder: 'Widget',
    Component,
    Settings: NotebookNodeGeneratedWidgetSettings,
    serializedText: () => 'Widget',
    heightEstimate: 420,
    minHeight: 180,
    resizeable: true,
    expandable: false,
    unmountWhenOutOfView: true,
    attributes: {
        prompt: { default: '' },
        model: { default: DEFAULT_WIDGET_MODEL },
    },
})
