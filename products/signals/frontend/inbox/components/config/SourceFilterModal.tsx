import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useId, useRef } from 'react'

import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { SourceFilterCatalogApi } from 'products/signals/frontend/generated/api.schemas'

import { SourceFilterModalLogicProps, sourceFilterModalLogic } from '../../logics/sourceFilterModalLogic'
import { SignalSourceConfig } from '../../types'
import { SourceFilterFieldList } from './SourceFilterFieldList'
import { SourceFilterFieldSnippets } from './SourceFilterFieldSnippets'
import { SourceFilterLinearTeams } from './SourceFilterLinearTeams'
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
        selectedField,
        selectedFieldName,
        teamsEditable,
        linearIntegration,
        integrationsUnknown,
        integrationsLoadFailed,
    } = useValues(logic)
    const { setSourceFilterValue, selectField, removeFilter, loadIntegrations } = useActions(logic)

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
            width={760}
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
                    <div className="flex flex-col gap-3 @min-[36rem]:flex-row">
                        <div className="@min-[36rem]:w-52 @min-[36rem]:shrink-0">
                            <SourceFilterFieldList
                                fields={catalog.filter_fields}
                                selectedFieldName={selectedFieldName}
                                onSelect={selectField}
                            />
                        </div>
                        <div className="flex min-w-0 flex-1 flex-col gap-2">
                            {selectedField && (
                                <SourceFilterFieldSnippets
                                    field={selectedField}
                                    onInsert={handleInsert}
                                    disabledReason={busy ? 'Saving' : undefined}
                                />
                            )}
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
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
