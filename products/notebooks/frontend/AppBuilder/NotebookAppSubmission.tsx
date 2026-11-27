import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonTable, Link } from '@posthog/lemon-ui'

import { uuid } from 'lib/utils/dom'
import { isUUIDLike } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import { cohortsFromSelectionCreate } from 'products/cohorts/frontend/generated/api'
import { hogFlowsRetrieve, hogFlowsRunCreate } from 'products/workflows/frontend/generated/api'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import {
    emptySubmissionDraft,
    notebookAppSubmissionLogic,
    type CellEdits,
    type EditableValue,
    type SubmissionDraft,
} from './notebookAppSubmissionLogic'

function SubmissionValue({
    value,
    original,
    label,
    editable,
    disabled,
    onEdit,
}: {
    value: unknown
    original: unknown
    label: string
    editable: boolean
    disabled: boolean
    onEdit: (value: EditableValue) => void
}): JSX.Element {
    if (editable) {
        if (typeof original === 'boolean') {
            return <LemonCheckbox aria-label={label} checked={value === true} disabled={disabled} onChange={onEdit} />
        }
        if (typeof original === 'number') {
            return (
                <LemonInput
                    type="number"
                    aria-label={label}
                    value={typeof value === 'number' ? value : undefined}
                    disabled={disabled}
                    onChange={(number) => onEdit(number ?? null)}
                />
            )
        }
        if (typeof original === 'string' || original == null) {
            return <LemonInput aria-label={label} value={String(value ?? '')} disabled={disabled} onChange={onEdit} />
        }
    }
    return <span>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}</span>
}

function displayedValue(edits: CellEdits, row: number, column: number, original: unknown): unknown {
    return edits[row] && column in edits[row] ? edits[row][column] : original
}

const workflowSizeError = 'Select fewer rows or shorten their values. Workflow inputs must fit within 5 KB.'

function workflowVariablesFit(variables: Record<string, unknown>): boolean {
    const json = JSON.stringify(variables)
    let size = json.length
    if (size > 5120) {
        return false
    }
    // Python's JSON encoder escapes non-ASCII code units and adds a space after each separator.
    for (const [token] of json.matchAll(/"(?:[^"\\]|\\.)*"|[:,]/g)) {
        size += token.length === 1 ? 1 : 5 * (token.match(/[^\u0000-\u007e]/g)?.length ?? 0)
    }
    return size <= 5120
}

async function submitWorkflowRows(
    project: string,
    workflowId: string,
    rows: Record<string, unknown>[],
    requestKey: string
): Promise<Partial<SubmissionDraft>> {
    if (!workflowVariablesFit({ rows })) {
        return { error: workflowSizeError }
    }
    const workflow = await hogFlowsRetrieve(project, workflowId)
    const defaults = Object.fromEntries(
        (workflow.variables ?? []).map((variable) => [variable.key, variable.default ?? null])
    )
    if (!workflowVariablesFit({ ...defaults, rows })) {
        return { error: workflowSizeError }
    }
    await hogFlowsRunCreate(
        project,
        workflowId,
        { variables: { rows } },
        { headers: { 'Idempotency-Key': requestKey } }
    )
    return { outcome: { title: 'View workflow runs', link: urls.workflow(workflowId, 'invocations') } }
}

function submissionError(cause: unknown): string {
    const detail = cause && typeof cause === 'object' && 'detail' in cause ? cause.detail : null
    if (String(detail ?? cause).includes('Total size of variable overrides')) {
        return workflowSizeError
    }
    return typeof detail === 'string' ? detail : 'Submission failed. Check your permissions and try again.'
}

function unavailableReason(
    cohort: boolean,
    name: string,
    selected: number,
    pending: boolean,
    completed: boolean
): string | undefined {
    if (completed) {
        return 'Already submitted'
    }
    if (pending) {
        return 'Refresh the results first'
    }
    if (!selected) {
        return 'Select at least one row'
    }
    if (selected > 1000) {
        return 'Select up to 1,000 rows'
    }
    if (cohort && !name.trim()) {
        return 'Enter a cohort name'
    }
}

type SubmissionProps = {
    sessionId: string
    draftKey: string
    action: NonNullable<NotebookAppBlockApi['submit_action']>
    project: string
    workflowId?: string
    columns: string[]
    rows: unknown[][]
    pendingInputs: boolean
}

export function NotebookAppSubmission(props: SubmissionProps): JSX.Element {
    const { action, columns, workflowId } = props
    if (action === 'create_cohort' && !columns.includes('person_id')) {
        return <LemonBanner type="warning">The SQL result needs a person_id column to create a cohort.</LemonBanner>
    }
    if (action === 'run_workflow' && (!workflowId || new Set(columns).size !== columns.length)) {
        return (
            <LemonBanner type="warning">
                Set a workflow ID and use unique SQL column names to run this workflow.
            </LemonBanner>
        )
    }
    return <SubmissionForm {...props} />
}

function SubmissionForm({
    sessionId,
    draftKey,
    action,
    project,
    workflowId,
    columns,
    rows,
    pendingInputs,
}: SubmissionProps): JSX.Element {
    const cohort = action === 'create_cohort'
    const logic = notebookAppSubmissionLogic({ sessionId })
    const { drafts } = useValues(logic)
    const { name, selected, edits, sending, error, outcome } = drafts[draftKey] ?? emptySubmissionDraft
    const update = (patch: Partial<SubmissionDraft>): void => {
        if (logic.isMounted()) {
            logic.actions.updateDraft(draftKey, patch)
        }
    }

    const personColumn = columns.indexOf('person_id')
    const table = useMemo(() => rows.map((values, index) => ({ values, index })), [rows])
    const busy = sending || !!outcome
    const rowCount = selected.length
    const buttonLabel = cohort ? 'Create cohort' : 'Run workflow'
    const disabledReason = unavailableReason(cohort, name, rowCount, pendingInputs, !!outcome)
    async function submit(): Promise<void> {
        const previous = logic.values.drafts[draftKey]
        if (previous?.sending || previous?.outcome || disabledReason) {
            return
        }
        update({ sending: true, error: '' })
        try {
            const personIds = cohort ? [...new Set(selected.map((index) => String(rows[index][personColumn])))] : []
            const records = cohort
                ? []
                : selected.map((index) =>
                      Object.fromEntries(
                          columns.map((column, i) => [column, displayedValue(edits, index, i, rows[index][i])])
                      )
                  )
            const payload = JSON.stringify([name.trim(), personIds, records])
            const request = previous?.request?.payload === payload ? previous.request : { key: uuid(), payload }
            update({ request })
            if (cohort) {
                const result = await cohortsFromSelectionCreate(project, {
                    name: name.trim(),
                    request_id: request.key,
                    person_ids: personIds,
                })
                update({ outcome: { title: 'Open cohort', link: urls.cohort(result.cohort_id) } })
            } else if (workflowId) {
                update(await submitWorkflowRows(project, workflowId, records, request.key))
            }
        } catch (cause) {
            update({ error: submissionError(cause) })
        } finally {
            update({ sending: false })
        }
    }

    return (
        <div className="flex flex-col gap-3 mb-2">
            <LemonTable
                dataSource={table}
                rowKey="index"
                size="small"
                pagination={{ pageSize: 10, hideOnSinglePage: true }}
                columns={[
                    {
                        title: 'Select',
                        key: 'selection',
                        width: 0,
                        render: (_, { index, values }) => (
                            <LemonCheckbox
                                aria-label={`Select row ${index + 1}`}
                                checked={selected.includes(index)}
                                disabledReason={
                                    busy
                                        ? 'Submission locked'
                                        : cohort && !isUUIDLike(String(values[personColumn]))
                                          ? 'This row needs a valid person ID'
                                          : undefined
                                }
                                onChange={(checked) =>
                                    update({
                                        selected: checked ? [...selected, index] : selected.filter((i) => i !== index),
                                    })
                                }
                            />
                        ),
                    },
                    ...columns.map((column, i) => ({
                        title: column,
                        key: String(i),
                        render: (_: unknown, { index, values }: { index: number; values: unknown[] }) => (
                            <SubmissionValue
                                label={`${column}, row ${index + 1}`}
                                original={values[i]}
                                value={displayedValue(edits, index, i, values[i])}
                                editable={!cohort && selected.includes(index)}
                                disabled={busy}
                                onEdit={(value) =>
                                    update({ edits: { ...edits, [index]: { ...edits[index], [i]: value } } })
                                }
                            />
                        ),
                    })),
                ]}
            />
            <div className="flex flex-wrap items-center gap-2">
                {cohort && (
                    <LemonInput
                        aria-label="Cohort name"
                        placeholder="Cohort name"
                        value={name}
                        onChange={(name) => update({ name })}
                        maxLength={400}
                        disabled={busy}
                    />
                )}
                <LemonButton
                    type="primary"
                    data-attr="notebook-app-submit-rows"
                    loading={sending}
                    disabledReason={disabledReason}
                    onClick={() => void submit()}
                >
                    {buttonLabel}
                </LemonButton>
                <span className="text-secondary">
                    {rowCount} {rowCount === 1 ? 'row' : 'rows'} selected
                </span>
            </div>
            {!cohort && workflowId && (
                <small>
                    Selected rows go to <Link to={urls.workflow(workflowId, 'workflow')}>this workflow</Link>. Select a
                    row to edit its values.
                </small>
            )}
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            {outcome && (
                <LemonBanner type="success">
                    {cohort ? 'Cohort created.' : 'Workflow queued.'} <Link to={outcome.link}>{outcome.title}</Link>
                </LemonBanner>
            )}
        </div>
    )
}
