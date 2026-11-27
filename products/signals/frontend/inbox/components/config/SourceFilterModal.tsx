import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useId, useRef } from 'react'

import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { SourceFilterCatalogApi } from 'products/signals/frontend/generated/api.schemas'

import { SourceFilterModalLogicProps, sourceFilterModalLogic } from '../../logics/sourceFilterModalLogic'
import { sourceFilterPreviewLogic } from '../../logics/sourceFilterPreviewLogic'
import { SignalSourceConfig } from '../../types'
import { SourceFilterFieldList } from './SourceFilterFieldList'
import { SourceFilterFieldSnippets } from './SourceFilterFieldSnippets'
import { SourceFilterLinearTeams } from './SourceFilterLinearTeams'
import { SourceFilterPreviewPanel } from './SourceFilterPreviewPanel'
import { SourceFilterSnippet, appendSnippet } from './sourceFilterSnippets'

export interface SourceFilterModalProps {
    sourceConfig: SignalSourceConfig
    catalog: SourceFilterCatalogApi
    /** The roster label of the source, for the title. */
    sourceLabel: string
    onClose: () => void
}

export function SourceFilterModal({
    sourceConfig,
    catalog,
    sourceLabel,
    onClose,
}: SourceFilterModalProps): JSX.Element {
    const formId = useId()
    const logicProps: SourceFilterModalLogicProps = { sourceConfig, catalog, onClose }
    const logic = sourceFilterModalLogic(logicProps)
    const {
        sourceFilter,
        sourceFilterChanged,
        isSourceFilterSubmitting,
        isRemovingFilter,
        savedFilter,
        savedOnOlderCatalog,
        previewWaitsForEdit,
        selectedField,
        selectedFieldName,
        teamsEditable,
        linearIntegration,
        integrationsUnknown,
        integrationsLoadFailed,
    } = useValues(logic)
    const { setSourceFilterValue, selectField, removeFilter, loadIntegrations } = useActions(logic)
    const previewLogic = sourceFilterPreviewLogic({ sourceConfig, catalog })
    const { previewResult, previewLoading, previewRequestError } = useValues(previewLogic)
    const { retryPreview } = useActions(previewLogic)

    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const pendingCursor = useRef<number | null>(null)

    useEffect(() => {
        const area = textAreaRef.current
        if (pendingCursor.current === null || !area) {
            return
        }
        area.focus()
        area.setSelectionRange(pendingCursor.current, pendingCursor.current)
        pendingCursor.current = null
    }, [sourceFilter.expression])

    const busy = isSourceFilterSubmitting || isRemovingFilter
    const noun = catalog.source_type
    const hasSavedFilter = !!savedFilter?.expression.trim()

    const handleClose = (): void => {
        if (!busy) {
            onClose()
        }
    }

    const handleInsert = (snippet: SourceFilterSnippet): void => {
        const result = appendSnippet(sourceFilter.expression, snippet)
        pendingCursor.current = result.cursor
        setSourceFilterValue('expression', result.expression)
    }

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title={`Filter ${sourceLabel} ${noun}s`}
            description={`Set a rule each ${sourceLabel} ${noun} must pass before the agent reads it. ${noun.charAt(0).toUpperCase()}${noun.slice(1)}s that don't pass are skipped before any AI work starts. Leave it empty to let every ${noun} through.`}
            width={catalog.preview_supported ? 1040 : 760}
            hasUnsavedInput={sourceFilterChanged}
            footer={
                <div className="flex w-full flex-wrap items-center justify-between gap-2">
                    {hasSavedFilter ? (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={removeFilter}
                            loading={isRemovingFilter}
                            disabledReason={isSourceFilterSubmitting ? 'Saving' : undefined}
                            data-attr="signal-source-filter-remove"
                        >
                            Remove filter
                        </LemonButton>
                    ) : (
                        <span />
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={handleClose}
                            disabledReason={busy ? 'Saving' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            form={formId}
                            htmlType="submit"
                            loading={isSourceFilterSubmitting}
                            disabledReason={isRemovingFilter ? 'Removing' : undefined}
                            data-attr="signal-source-filter-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <Form
                logic={sourceFilterModalLogic}
                props={logicProps}
                formKey="sourceFilter"
                id={formId}
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-3 @container">
                    {savedOnOlderCatalog && (
                        <LemonBanner type="info">
                            This filter was saved before the {sourceLabel} fields last changed. It keeps working as
                            saved. Editing it checks it against the current fields.
                        </LemonBanner>
                    )}
                    <div className="flex flex-col gap-4 @3xl:flex-row">
                        <div className="flex min-w-0 flex-1 flex-col gap-3 @container">
                            {teamsEditable && (
                                <SourceFilterLinearTeams
                                    scope={sourceFilter.teamScope}
                                    linearIntegration={linearIntegration}
                                    integrationsUnknown={integrationsUnknown}
                                    integrationsLoadFailed={integrationsLoadFailed}
                                    onRetryIntegrations={() => loadIntegrations()}
                                    disabledReason={busy ? 'Saving' : undefined}
                                />
                            )}
                            <div className="grid grid-cols-1 gap-3 @md:grid-cols-[13rem_minmax(0,1fr)]">
                                <SourceFilterFieldList
                                    fields={catalog.filter_fields}
                                    selectedFieldName={selectedFieldName}
                                    onSelect={selectField}
                                />
                                {selectedField && (
                                    <div className="min-w-0">
                                        <SourceFilterFieldSnippets
                                            field={selectedField}
                                            onInsert={handleInsert}
                                            disabledReason={busy ? 'Saving' : undefined}
                                        />
                                    </div>
                                )}
                            </div>
                            <LemonField
                                name="expression"
                                label="Filter"
                                help="Applies from the next sync. Reports already in your inbox stay."
                            >
                                {({ value, onChange }) => (
                                    <LemonTextArea
                                        ref={textAreaRef}
                                        className="font-mono text-xs"
                                        value={value}
                                        onChange={onChange}
                                        minRows={5}
                                        maxRows={12}
                                        disabled={busy}
                                        placeholder={catalog.starter_expressions[0]}
                                        data-attr="signal-source-filter-expression"
                                    />
                                )}
                            </LemonField>
                        </div>
                        {catalog.preview_supported && (
                            <div className="min-w-0 flex-1 @3xl:border-l @3xl:pl-4">
                                {previewWaitsForEdit ? (
                                    <LemonBanner type="info">
                                        {`The preview checks the current ${sourceLabel} fields, but this filter was saved on older ones. Edit the filter to preview it.`}
                                    </LemonBanner>
                                ) : (
                                    <SourceFilterPreviewPanel
                                        result={previewResult}
                                        loading={previewLoading}
                                        requestError={previewRequestError}
                                        onRetry={retryPreview}
                                        sourceLabel={sourceLabel}
                                        noun={noun}
                                    />
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
