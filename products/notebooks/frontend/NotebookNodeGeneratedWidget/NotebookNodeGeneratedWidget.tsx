import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { useComponentPanelState } from 'lib/components/MarkdownNotebook/componentPanelContext'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { NotebookNodeAttributes, NotebookNodeProps, NotebookNodeType } from 'scenes/notebooks/types'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    formatWidgetElapsed,
    loadWidgetFrame,
    notebookNodeGeneratedWidgetLogic,
} from './notebookNodeGeneratedWidgetLogic'
import { NotebookNodeGeneratedWidgetSettings } from './NotebookNodeGeneratedWidgetSettings'
import { NotebookWidgetSourceModal } from './NotebookWidgetSourceModal'
import { NotebookWidgetTrustControls } from './NotebookWidgetTrustControls'
import { getNotebookWidgetTrust, notebookWidgetTrustLogic } from './notebookWidgetTrustLogic'
import { WidgetArtifactFrame } from './WidgetArtifactFrame'
import { DEFAULT_WIDGET_MODEL, type WidgetModel } from './widgetModels'
import { getWidgetName } from './widgetName'

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
    const { expanded } = useValues(nodeLogic)

    return expanded ? <ExpandedWidget attributes={attributes} /> : null
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
    const logicProps = {
        projectId: currentTeamId,
        notebookShortId,
        nodeId: attributes.nodeId,
        prompt: attributes.prompt ?? '',
        model: attributes.model ?? DEFAULT_WIDGET_MODEL,
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

    const initialPrompt = (attributes.prompt ?? '').trim()
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
            <EmptyState>
                <div className="flex flex-col items-center gap-3">
                    <div>This widget's preview didn't load.</div>
                    <LemonButton onClick={refreshData} loading={dataRefreshInFlight}>
                        Reload preview
                    </LemonButton>
                </div>
            </EmptyState>
        )
    }

    if (selectedArtifactUrl && selectedVersionId && currentTeamId) {
        if (selectedSecurityReview?.severity !== 'none' && !widgetTrust.buildTrusted) {
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
                        <LemonBanner type="error" className="m-2">
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
                            {runtimeError}
                        </LemonBanner>
                    ) : null}
                    <div className="min-h-0 flex-1">
                        <WidgetArtifactFrame
                            key={`${selectedBuildHash}-${frameRevision}`}
                            artifactUrl={selectedArtifactUrl}
                            title={getWidgetName(attributes.prompt ?? '')}
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
                                artifactAvailable()
                                setRuntimeError(null)
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
                                onClick={() =>
                                    generateWidget(initialPrompt, attributes.model ?? DEFAULT_WIDGET_MODEL, 'initial')
                                }
                                loading={generationRequestLoading}
                            >
                                Generate widget
                            </LemonButton>
                        )
                    ) : null}
                </div>
            </EmptyState>
        )
    }

    if (status?.has_versions && versionsError && !versionsLoading && !selectedVersion) {
        return (
            <EmptyState>
                <div className="flex flex-col items-center gap-3">
                    <div>We couldn't load this widget version.</div>
                    <LemonButton onClick={() => loadVersions(true)}>Retry</LemonButton>
                </div>
            </EmptyState>
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
    if (selectedVersion) {
        return (
            <EmptyState>
                {isEditable
                    ? "This version's preview is no longer available. Its prompt and source remain in version history."
                    : "This version's preview is no longer available."}
            </EmptyState>
        )
    }
    return (
        <EmptyState>
            <div className="flex flex-col items-center gap-3">
                <div>This widget has not been generated yet.</div>
                {isEditable ? (
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            generateWidget(initialPrompt, attributes.model ?? DEFAULT_WIDGET_MODEL, 'initial')
                        }
                        loading={generationRequestLoading}
                    >
                        Generate widget
                    </LemonButton>
                ) : null}
            </div>
        </EmptyState>
    )
}

export const NotebookNodeGeneratedWidget = createPostHogWidgetNode<NotebookNodeGeneratedWidgetAttributes>({
    nodeType: NotebookNodeType.GeneratedWidget,
    titlePlaceholder: 'Widget',
    Component,
    Settings: NotebookNodeGeneratedWidgetSettings,
    serializedText: (attributes) => getWidgetName(attributes.prompt ?? ''),
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
