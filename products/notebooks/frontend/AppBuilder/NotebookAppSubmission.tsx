import { useMemo, useRef, useState } from 'react'

import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonTable, Link } from '@posthog/lemon-ui'

import { uuid } from 'lib/utils/dom'
import { isUUIDLike } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import { cohortsFromSelectionCreate } from 'products/cohorts/frontend/generated/api'
import { hogFlowsRunCreate } from 'products/workflows/frontend/generated/api'

import type { NotebookAppBlockApi } from '../generated/api.schemas'

type EditableValue = string | number | boolean | null

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

type CellEdits = Record<number, Record<number, EditableValue>>

function displayedValue(edits: CellEdits, row: number, column: number, original: unknown): unknown {
    return edits[row] && column in edits[row] ? edits[row][column] : original
}

function submissionError(cause: unknown): string {
    const detail = cause && typeof cause === 'object' && 'detail' in cause ? cause.detail : null
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

function SubmissionForm({ action, project, workflowId, columns, rows, pendingInputs }: SubmissionProps): JSX.Element {
    const cohort = action === 'create_cohort'
    const [name, setName] = useState('')
    const [selected, setSelected] = useState<number[]>([])
    const [edits, setEdits] = useState<CellEdits>({})
    const [sending, setSending] = useState(false)
    const [error, setError] = useState('')
    const [outcome, setOutcome] = useState<{ title: string; link: string }>()
    const request = useRef<{ key: string; payload: string } | null>(null)
    const inFlight = useRef(false)

    const personColumn = columns.indexOf('person_id')
    const table = useMemo(() => rows.map((values, index) => ({ values, index })), [rows])
    const busy = sending || !!outcome
    const rowCount = selected.length
    const buttonLabel = cohort ? 'Create cohort' : 'Run workflow'
    const disabledReason = unavailableReason(cohort, name, rowCount, pendingInputs, !!outcome)
    async function submit(): Promise<void> {
        if (inFlight.current || disabledReason) {
            return
        }
        inFlight.current = true
        setSending(true)
        setError('')
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
            if (request.current?.payload !== payload) {
                request.current = { key: uuid(), payload }
            }
            if (cohort) {
                const result = await cohortsFromSelectionCreate(project, {
                    name: name.trim(),
                    request_id: request.current.key,
                    person_ids: personIds,
                })
                setOutcome({ title: 'Open cohort', link: urls.cohort(result.cohort_id) })
            } else if (workflowId) {
                await hogFlowsRunCreate(
                    project,
                    workflowId,
                    { variables: { rows: records } },
                    {
                        headers: { 'Idempotency-Key': request.current.key },
                    }
                )
                setOutcome({ title: 'View workflow runs', link: urls.workflow(workflowId, 'invocations') })
            }
        } catch (cause) {
            setError(submissionError(cause))
        } finally {
            inFlight.current = false
            setSending(false)
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
                                    setSelected((prev) =>
                                        checked ? [...prev, index] : prev.filter((i) => i !== index)
                                    )
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
                                    setEdits((prev) => ({ ...prev, [index]: { ...prev[index], [i]: value } }))
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
                        onChange={setName}
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
