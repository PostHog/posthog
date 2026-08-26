import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import type { NotebookNodeAttributeProperties } from 'scenes/notebooks/types'

import type { NotebookNodeGeneratedWidgetAttributes } from './NotebookNodeGeneratedWidget'
import { formatWidgetElapsed, notebookNodeGeneratedWidgetLogic } from './notebookNodeGeneratedWidgetLogic'
import { DEFAULT_WIDGET_MODEL, WIDGET_MODEL_OPTIONS } from './widgetModels'

export function NotebookNodeGeneratedWidgetSettings({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeGeneratedWidgetAttributes>): JSX.Element {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { isEditable, notebookLogic } = useValues(nodeLogic)
    const logic = notebookNodeGeneratedWidgetLogic({
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
    })
    const {
        cancellationInFlight,
        elapsedSeconds,
        generationDraftLoading,
        generationDraftModel,
        generationDraftPrompt,
        generationError,
        generationModalOperation,
        generationRequestLoading,
        isWorking,
        restoreInFlight,
        selectedVersion,
        selectedVersionId,
        sourceDraft,
        sourceError,
        sourceLoading,
        sourceModalOpen,
        sourceNote,
        sourceSaving,
        status,
        versions,
        versionsCount,
        versionsLoading,
        versionsNextOffset,
        workingStatus,
    } = useValues(logic)
    const {
        cancelGeneration,
        closeGenerationModal,
        closeSourceEditor,
        generateWidget,
        loadMoreVersions,
        openGenerationModal,
        openSourceEditor,
        refreshData,
        restoreSelectedVersion,
        saveSource,
        selectVersion,
        setGenerationDraftModel,
        setGenerationDraftPrompt,
        setSourceDraft,
        setSourceNote,
    } = useActions(logic)
    const promptId = `widget-prompt-${attributes.nodeId}`
    const modelId = `widget-model-${attributes.nodeId}`
    const versionId = `widget-version-${attributes.nodeId}`
    const modalPromptId = `widget-change-prompt-${attributes.nodeId}`
    const modalModelId = `widget-change-model-${attributes.nodeId}`
    const sourceNoteId = `widget-source-note-${attributes.nodeId}`
    const hasVersions = Boolean(status?.has_versions)
    const isCurrentVersion = selectedVersionId === status?.current_version_id
    const initialPrompt = attributes.prompt ?? ''
    const modalTitle = generationModalOperation === 'improve' ? 'Improve widget' : 'Regenerate widget'
    const modalDescription =
        generationModalOperation === 'improve'
            ? 'Describe one change. The generator will update the current source and preserve everything else.'
            : 'Edit the complete instructions below. This creates a new widget from scratch and keeps the existing versions.'
    const sourceIsEditable = isEditable && isCurrentVersion
    const submitGenerationDraft = (prompt: string): void => {
        if (
            !generationModalOperation ||
            !prompt.trim() ||
            generationRequestLoading ||
            generationDraftLoading ||
            isWorking
        ) {
            return
        }
        generateWidget(prompt, generationDraftModel, generationModalOperation)
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
                            placeholder="Describe the widget you want to generate."
                            minRows={5}
                            autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                            disabled={!isEditable || isWorking}
                            className="mt-1 ph-no-capture"
                        />
                    </div>
                    <div className="text-xs text-muted">
                        Results from SQL and Python cells in this notebook are available automatically.
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
                    </div>
                    {selectedVersion ? (
                        <div className="rounded border bg-surface-primary p-3">
                            <div className="mb-1 text-xs font-semibold text-secondary">
                                {selectedVersion.operation === 'improve'
                                    ? 'Change made'
                                    : selectedVersion.operation === 'source_edit'
                                      ? 'Source change'
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
                        {status?.active_job ? (
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
                            <LemonButton type="primary" onClick={() => openGenerationModal('improve')}>
                                Improve...
                            </LemonButton>
                        ) : null}
                        {isEditable ? (
                            <LemonButton onClick={() => openGenerationModal('regenerate')}>Regenerate…</LemonButton>
                        ) : null}
                        <LemonButton onClick={openSourceEditor}>
                            {sourceIsEditable ? 'View or edit source' : 'View source'}
                        </LemonButton>
                        <LemonButton onClick={refreshData} data-attr="widget-reload-data">
                            Reload data
                        </LemonButton>
                    </>
                ) : (
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            generateWidget(initialPrompt, attributes.model ?? DEFAULT_WIDGET_MODEL, 'initial')
                        }
                        disabledReason={!initialPrompt.trim() ? 'Add instructions first' : undefined}
                        loading={generationRequestLoading}
                    >
                        Generate widget
                    </LemonButton>
                )}
            </div>
            {generationError || status?.error_detail ? (
                <div className="text-xs text-danger">{generationError || status?.error_detail}</div>
            ) : null}

            <LemonModal
                isOpen={generationModalOperation !== null}
                onClose={closeGenerationModal}
                title={modalTitle}
                description={modalDescription}
                width={640}
                footer={
                    <>
                        <LemonButton onClick={closeGenerationModal}>Cancel</LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => submitGenerationDraft(generationDraftPrompt)}
                            disabledReason={
                                generationDraftLoading
                                    ? 'Loading the current instructions'
                                    : !generationDraftPrompt.trim()
                                      ? 'Add instructions first'
                                      : undefined
                            }
                            loading={generationRequestLoading}
                        >
                            {generationModalOperation === 'improve' ? 'Improve' : 'Regenerate'}
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-4">
                    <div>
                        <LemonLabel htmlFor={modalPromptId}>
                            {generationModalOperation === 'improve' ? 'Change to make' : 'Full instructions'}
                        </LemonLabel>
                        <LemonTextArea
                            id={modalPromptId}
                            value={generationDraftPrompt}
                            onChange={setGenerationDraftPrompt}
                            onPressCmdEnter={submitGenerationDraft}
                            minRows={6}
                            autoFocus
                            disabled={generationDraftLoading}
                            className="mt-1 ph-no-capture"
                            placeholder={
                                generationModalOperation === 'improve'
                                    ? 'For example, make the colors lighter and increase the label contrast.'
                                    : 'Describe the complete widget.'
                            }
                        />
                    </div>
                    <div>
                        <LemonLabel htmlFor={modalModelId}>Model</LemonLabel>
                        <LemonSelect
                            id={modalModelId}
                            value={generationDraftModel}
                            options={WIDGET_MODEL_OPTIONS}
                            onChange={setGenerationDraftModel}
                            fullWidth
                            className="mt-1"
                        />
                    </div>
                </div>
            </LemonModal>

            <LemonModal
                isOpen={sourceModalOpen}
                onClose={closeSourceEditor}
                title={sourceIsEditable ? 'View or edit source' : 'View source'}
                description={
                    sourceIsEditable
                        ? 'Saving source creates a new version. The previous source remains in history.'
                        : isEditable
                          ? 'Restore this version before editing its source.'
                          : 'This source is read-only.'
                }
                width={960}
                footer={
                    <>
                        <LemonButton onClick={closeSourceEditor}>Close</LemonButton>
                        {sourceIsEditable ? (
                            <LemonButton
                                type="primary"
                                onClick={saveSource}
                                loading={sourceSaving}
                                disabledReason={
                                    !sourceDraft.trim()
                                        ? 'Source cannot be empty'
                                        : !sourceNote.trim()
                                          ? 'Describe your change first'
                                          : undefined
                                }
                            >
                                Save as new version
                            </LemonButton>
                        ) : null}
                    </>
                }
            >
                <div className="flex flex-col gap-3">
                    {sourceError ? <LemonBanner type="error">{sourceError}</LemonBanner> : null}
                    {sourceLoading ? (
                        <div className="flex h-80 items-center justify-center">
                            <Spinner />
                        </div>
                    ) : (
                        <CodeEditor
                            className="ph-no-capture rounded border"
                            language="typescript"
                            value={sourceDraft}
                            onChange={(value) => setSourceDraft(value ?? '')}
                            height="55vh"
                            path={`notebook-widget/${attributes.nodeId}/${selectedVersionId ?? 'current'}.tsx`}
                            options={{ readOnly: !sourceIsEditable, minimap: { enabled: false } }}
                        />
                    )}
                    {sourceIsEditable && !sourceLoading ? (
                        <div>
                            <LemonLabel htmlFor={sourceNoteId}>Change description</LemonLabel>
                            <LemonTextArea
                                id={sourceNoteId}
                                value={sourceNote}
                                onChange={setSourceNote}
                                placeholder="Describe what you changed."
                                minRows={2}
                                className="mt-1 ph-no-capture"
                            />
                        </div>
                    ) : null}
                </div>
            </LemonModal>
        </div>
    )
}
