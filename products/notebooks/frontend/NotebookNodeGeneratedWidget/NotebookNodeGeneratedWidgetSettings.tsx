import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import type { NotebookNodeAttributeProperties } from 'scenes/notebooks/types'
import { teamLogic } from 'scenes/teamLogic'

import type { NotebookNodeGeneratedWidgetAttributes } from './NotebookNodeGeneratedWidget'
import {
    formatWidgetElapsed,
    type NotebookNodeGeneratedWidgetLogicProps,
    notebookNodeGeneratedWidgetLogic,
    notebookNodeGeneratedWidgetSettingsLogic,
} from './notebookNodeGeneratedWidgetLogic'
import { NotebookWidgetGenerationModal } from './NotebookWidgetGenerationModal'
import { NotebookWidgetSourceModal } from './NotebookWidgetSourceModal'
import { DEFAULT_WIDGET_MODEL, DEFAULT_WIDGET_PROMPT, WIDGET_MODEL_OPTIONS } from './widgetModels'

export function NotebookNodeGeneratedWidgetSettings({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeGeneratedWidgetAttributes>): JSX.Element {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { isEditable, notebookLogic } = useValues(nodeLogic)
    const { currentTeamId } = useValues(teamLogic)
    const logicProps: NotebookNodeGeneratedWidgetLogicProps = {
        projectId: currentTeamId,
        notebookShortId: notebookLogic.props.shortId,
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
    useMountedLogic(notebookNodeGeneratedWidgetSettingsLogic(logicProps))
    const logic = notebookNodeGeneratedWidgetLogic(logicProps)
    const {
        cancellationInFlight,
        elapsedSeconds,
        generationError,
        generationRequestLoading,
        isWorking,
        dataRefreshInFlight,
        restoreInFlight,
        selectedVersion,
        selectedVersionId,
        status,
        statusLoadError,
        statusLoading,
        versions,
        versionsCount,
        versionsError,
        versionsLoading,
        versionsNextOffset,
        workingStatus,
    } = useValues(logic)
    const {
        cancelGeneration,
        clearGenerationError,
        generateWidget,
        loadMoreVersions,
        loadStatus,
        loadVersions,
        openGenerationModal,
        openSourceModal,
        refreshData,
        restoreSelectedVersion,
        selectVersion,
    } = useActions(logic)
    const promptId = `widget-prompt-${attributes.nodeId}`
    const modelId = `widget-model-${attributes.nodeId}`
    const versionId = `widget-version-${attributes.nodeId}`
    const hasVersions = Boolean(status?.has_versions)
    const isCurrentVersion = selectedVersionId === status?.current_version_id
    const initialPrompt = attributes.prompt ?? ''
    const visibleGenerationError =
        generationError || (!isWorking && !generationRequestLoading ? status?.error_detail : null)

    // A null status means the first status response has not arrived. Never show the initial
    // generation form here, or an editor could start a job on a widget that already has versions
    // (the backend turns that "initial" request into a regeneration). The node body guards the
    // same window; mirror it with a loading, then retry, state.
    if (!status) {
        if (statusLoadError) {
            return (
                <div className="flex flex-col items-start gap-3 p-3">
                    <div className="text-sm">We couldn't load this widget's status.</div>
                    <LemonButton onClick={loadStatus} loading={statusLoading}>
                        Retry
                    </LemonButton>
                </div>
            )
        }
        return (
            <div className="flex flex-col gap-3 p-3">
                <LemonSkeleton className="h-6 w-1/3" />
                <LemonSkeleton className="h-20 w-full" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3 p-3">
            {!hasVersions ? (
                <>
                    <div>
                        <LemonLabel htmlFor={promptId}>Instructions</LemonLabel>
                        <LemonTextArea
                            id={promptId}
                            value={initialPrompt}
                            onChange={(value) => updateAttributes({ prompt: value || undefined })}
                            placeholder={DEFAULT_WIDGET_PROMPT}
                            minRows={5}
                            autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                            disabled={!isEditable || isWorking}
                            className="mt-1 ph-no-capture"
                        />
                    </div>
                    <div className="text-xs text-muted">
                        Run every SQL and Python cell before generating. The widget can use their latest completed
                        results automatically.
                    </div>
                    <div>
                        <LemonLabel htmlFor={modelId}>Model</LemonLabel>
                        <LemonSelect
                            id={modelId}
                            value={attributes.model ?? DEFAULT_WIDGET_MODEL}
                            options={WIDGET_MODEL_OPTIONS}
                            onChange={(model) => updateAttributes({ model })}
                            fullWidth
                            disabled={!isEditable || isWorking}
                            className="mt-1"
                            data-attr="widget-model-select"
                        />
                    </div>
                </>
            ) : (
                <>
                    <div>
                        <LemonLabel htmlFor={versionId}>Version history</LemonLabel>
                        <LemonSelect
                            id={versionId}
                            value={selectedVersionId ?? undefined}
                            options={versions.map((version) => ({
                                value: version.id,
                                label: `Version ${version.version}${
                                    version.is_current ? ' (current)' : ''
                                } · ${humanFriendlyDetailedTime(version.created_at)}`,
                            }))}
                            onChange={selectVersion}
                            fullWidth
                            loading={versionsLoading}
                            className="mt-1"
                            data-attr="widget-version-select"
                        />
                        <div className="mt-1 flex items-center justify-between text-xs text-muted">
                            <span>
                                {versions.length} of {versionsCount} versions loaded
                            </span>
                            {versionsNextOffset !== null ? (
                                <LemonButton size="xsmall" onClick={loadMoreVersions} loading={versionsLoading}>
                                    Load older versions
                                </LemonButton>
                            ) : null}
                        </div>
                        {versionsError && !versionsLoading ? (
                            <LemonBanner
                                type="warning"
                                className="mt-2"
                                action={{ children: 'Retry', onClick: () => loadVersions(true) }}
                            >
                                Couldn't load version history.
                            </LemonBanner>
                        ) : null}
                    </div>
                    {selectedVersion ? (
                        <div className="rounded border bg-surface-primary p-3">
                            <div className="mb-1 text-xs font-semibold text-secondary">
                                {selectedVersion.version_operation === 'improve'
                                    ? 'Change made'
                                    : 'Instructions for this version'}
                            </div>
                            <div className="ph-no-capture max-h-48 overflow-auto whitespace-pre-wrap text-sm">
                                {selectedVersion.prompt_delta || 'No instructions were recorded for this version.'}
                            </div>
                        </div>
                    ) : null}
                </>
            )}

            <div className="flex flex-wrap items-start gap-2">
                {isWorking && workingStatus ? (
                    <>
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <div className="flex flex-wrap items-center gap-2 text-sm text-secondary">
                                <span className="flex items-center gap-2" role="status" aria-live="polite">
                                    <Spinner />
                                    <span>{workingStatus.label}</span>
                                </span>
                                <span
                                    className="font-mono tabular-nums"
                                    aria-hidden="true"
                                    data-attr="widget-elapsed-time"
                                >
                                    {formatWidgetElapsed(elapsedSeconds)}
                                </span>
                            </div>
                            <span className="text-xs text-muted">{workingStatus.detail}</span>
                            <span
                                className={workingStatus.isOverEstimate ? 'text-xs text-warning' : 'text-xs text-muted'}
                            >
                                {workingStatus.timing}
                            </span>
                        </div>
                        {status?.active_job && isEditable ? (
                            <LemonButton onClick={cancelGeneration} loading={cancellationInFlight}>
                                Cancel
                            </LemonButton>
                        ) : null}
                    </>
                ) : hasVersions ? (
                    <>
                        {!isCurrentVersion && isEditable ? (
                            <LemonButton onClick={restoreSelectedVersion} loading={restoreInFlight}>
                                Restore as new version
                            </LemonButton>
                        ) : null}
                        {isCurrentVersion && isEditable ? (
                            <>
                                <LemonButton
                                    type="primary"
                                    onClick={() => openGenerationModal('improve')}
                                    disabledReason={!selectedVersion ? 'Loading the widget version.' : undefined}
                                >
                                    Improve…
                                </LemonButton>
                                <LemonButton
                                    onClick={() => openGenerationModal('regenerate')}
                                    disabledReason={!selectedVersion ? 'Loading the widget version.' : undefined}
                                >
                                    Regenerate…
                                </LemonButton>
                                <LemonButton onClick={openSourceModal} data-attr="notebook-widget-view-source">
                                    View source
                                </LemonButton>
                                <LemonButton
                                    onClick={refreshData}
                                    disabledReason={dataRefreshInFlight ? 'Reloading preview.' : undefined}
                                    data-attr="notebook-widget-reload"
                                >
                                    Reload preview
                                </LemonButton>
                            </>
                        ) : null}
                        {!isCurrentVersion && isEditable ? (
                            <LemonButton
                                onClick={() => openGenerationModal('regenerate')}
                                disabledReason={!selectedVersion ? 'Loading the widget version.' : undefined}
                            >
                                Regenerate…
                            </LemonButton>
                        ) : null}
                    </>
                ) : (
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            generateWidget(initialPrompt, attributes.model ?? DEFAULT_WIDGET_MODEL, 'initial')
                        }
                        loading={generationRequestLoading}
                        disabledReason={!isEditable ? 'You need edit access to generate a widget.' : undefined}
                    >
                        Generate widget
                    </LemonButton>
                )}
            </div>
            {visibleGenerationError ? (
                <LemonBanner type="error" onClose={generationError ? clearGenerationError : undefined}>
                    {visibleGenerationError}
                </LemonBanner>
            ) : null}

            <NotebookWidgetGenerationModal logicProps={logicProps} />
            <NotebookWidgetSourceModal {...logicProps} />
        </div>
    )
}
