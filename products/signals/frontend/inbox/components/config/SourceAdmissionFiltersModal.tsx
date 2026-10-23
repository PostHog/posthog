import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { AdmissionFilterRow, AdmissionMatch, emptyAdmissionFilterRow } from '../../admissionRules'
import {
    SourceAdmissionFiltersModalLogicProps,
    sourceAdmissionFiltersModalLogic,
} from '../../logics/sourceAdmissionFiltersModalLogic'
import { SignalSourceConfig, SignalSourceProduct, linearTeamIdsFromConfig } from '../../types'
import { SourceAdmissionFilterRow } from './SourceAdmissionFilterRow'
import { SourceAdmissionPreview } from './SourceAdmissionPreview'

export interface SourceAdmissionFiltersModalProps {
    sourceConfig: SignalSourceConfig
    /** The roster label of the source, for the modal title. */
    sourceLabel: string
    onClose: () => void
}

export function SourceAdmissionFiltersModal({
    sourceConfig,
    sourceLabel,
    onClose,
}: SourceAdmissionFiltersModalProps): JSX.Element {
    const formId = useId()
    const logicProps: SourceAdmissionFiltersModalLogicProps = { sourceConfig, onClose }
    const logic = sourceAdmissionFiltersModalLogic(logicProps)
    const {
        admissionFilters,
        admissionFiltersChanged,
        admissionFiltersValidationErrors,
        showAdmissionFiltersErrors,
        isAdmissionFiltersSubmitting,
        fields,
        hasUnsupportedStoredRules,
    } = useValues(logic)
    const { setAdmissionFiltersValue, setAdmissionFiltersValues, submitAdmissionFilters } = useActions(logic)

    const { rows, match } = admissionFilters
    const hadStoredRules = sourceConfig.config?.admission_rules != null
    const linearTeamCount =
        sourceConfig.source_product === SignalSourceProduct.Linear
            ? linearTeamIdsFromConfig(sourceConfig.config).length
            : 0
    const rowErrors = (admissionFiltersValidationErrors.rows ?? []) as ({ field?: string } | undefined)[]

    const handleClose = (): void => {
        if (!isAdmissionFiltersSubmitting) {
            onClose()
        }
    }

    const setRows = (next: AdmissionFilterRow[]): void => setAdmissionFiltersValue('rows', next)

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title={`Filters for ${sourceLabel}`}
            description="Only issues that match these filters go on to AI review. Filters apply from the next sync. They don't change reports already in your inbox, and they aren't a spending limit."
            width={640}
            hasUnsavedInput={admissionFiltersChanged}
            footer={
                <div className="flex w-full flex-wrap items-center justify-between gap-2">
                    {hadStoredRules ? (
                        <LemonButton
                            type="tertiary"
                            status="danger"
                            onClick={() => {
                                setAdmissionFiltersValues({ rows: [] })
                                submitAdmissionFilters()
                            }}
                            disabledReason={isAdmissionFiltersSubmitting ? 'Saving' : undefined}
                            data-attr="signal-source-admission-filters-clear"
                        >
                            Clear filters
                        </LemonButton>
                    ) : (
                        <span />
                    )}
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={handleClose}
                            disabledReason={isAdmissionFiltersSubmitting ? 'Saving' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            form={formId}
                            htmlType="submit"
                            loading={isAdmissionFiltersSubmitting}
                            data-attr="signal-source-admission-filters-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <Form
                logic={sourceAdmissionFiltersModalLogic}
                props={logicProps}
                formKey="admissionFilters"
                id={formId}
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-3">
                    {hasUnsupportedStoredRules && (
                        <LemonBanner type="warning">
                            These filters were set through the API with nested groups, which this form can't show.
                            Saving here replaces them.
                        </LemonBanner>
                    )}
                    {linearTeamCount > 0 && (
                        <span className="text-xs text-secondary">
                            Filters apply within the {linearTeamCount} Linear {linearTeamCount === 1 ? 'team' : 'teams'}{' '}
                            you picked.
                        </span>
                    )}
                    {rows.length > 1 && (
                        <div className="flex items-center gap-2">
                            <span className="text-sm">Issues must match</span>
                            <LemonSegmentedButton<AdmissionMatch>
                                size="small"
                                value={match}
                                onChange={(value) => setAdmissionFiltersValue('match', value)}
                                options={[
                                    { value: 'AND', label: 'All filters' },
                                    { value: 'OR', label: 'Any filter' },
                                ]}
                            />
                        </div>
                    )}
                    {rows.length === 0 ? (
                        <span className="text-sm text-secondary">
                            No filters. Every issue this source reads goes on to AI review.
                        </span>
                    ) : (
                        rows.map((row, index) => (
                            <SourceAdmissionFilterRow
                                key={index}
                                row={row}
                                fields={fields}
                                error={showAdmissionFiltersErrors ? rowErrors[index]?.field : undefined}
                                disabled={isAdmissionFiltersSubmitting}
                                onChange={(next) => setRows(rows.map((r, i) => (i === index ? next : r)))}
                                onRemove={() => setRows(rows.filter((_, i) => i !== index))}
                            />
                        ))
                    )}
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => setRows([...rows, emptyAdmissionFilterRow(fields[0])])}
                            disabledReason={
                                isAdmissionFiltersSubmitting
                                    ? 'Saving'
                                    : rows.length >= 20
                                      ? 'You can add up to 20 filters'
                                      : undefined
                            }
                            data-attr="signal-source-admission-filters-add-row"
                        >
                            Add filter
                        </LemonButton>
                        <span className="text-xs text-secondary">Values match exactly, and case matters.</span>
                    </div>
                    <SourceAdmissionPreview logicProps={logicProps} />
                </div>
            </Form>
        </LemonModal>
    )
}
