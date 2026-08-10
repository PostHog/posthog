import { useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { AIEnrichmentRunRow, aiEnrichmentLogic } from './aiEnrichmentLogic'
import {
    OutputColumnSpec,
    deriveOutputColumns,
    isSkippedRow,
    summarizeError,
    summarizeInputs,
} from './aiEnrichmentResultColumns'

function outputCell(row: AIEnrichmentRunRow, column: OutputColumnSpec): JSX.Element | string | null {
    if (row.outputs === null) {
        return <span className="text-secondary">–</span>
    }
    const value = row.outputs[column.key]
    if (value === undefined) {
        return <span className="text-secondary">–</span>
    }
    // Checked before the column's declared type: a skipped/indeterminate row can land in any
    // typed column, and a boolean column would otherwise render its sentinel as a truthy green
    // tag indistinguishable from a real positive verdict.
    if (isSkippedRow(row)) {
        return <LemonTag type="muted">unknown</LemonTag>
    }
    if (column.type === 'boolean') {
        return <LemonTag type={value ? 'success' : 'danger'}>{String(value)}</LemonTag>
    }
    if (column.type === 'number') {
        return <div className="text-right tabular-nums">{value}</div>
    }
    return (
        <Tooltip title={String(value)}>
            <div className="truncate max-w-xs">{String(value)}</div>
        </Tooltip>
    )
}

function columnTitle(key: string): string {
    const spaced = key.replace(/_/g, ' ')
    return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function buildColumns(rows: AIEnrichmentRunRow[]): LemonTableColumns<AIEnrichmentRunRow> {
    const outputColumns = deriveOutputColumns(rows)
    const hasErrorRows = rows.some((row) => row.outputs === null)

    const columns: LemonTableColumns<AIEnrichmentRunRow> = [
        { title: 'Company', key: 'company', dataIndex: 'company' },
        {
            title: 'Domain',
            key: 'domain',
            render: (_, row) => row.domain ?? <span className="text-secondary">–</span>,
        },
        {
            title: 'Inputs sent',
            key: 'inputs',
            render: (_, row) => {
                const summary = summarizeInputs(row.inputs)
                return summary ? (
                    <Tooltip title={summary}>
                        <div className="truncate max-w-xs text-secondary text-xs">{summary}</div>
                    </Tooltip>
                ) : (
                    <span className="text-secondary">–</span>
                )
            },
        },
        ...outputColumns.map((column) => ({
            title: columnTitle(column.key),
            key: column.key,
            align: column.type === 'number' ? ('right' as const) : undefined,
            render: (_: unknown, row: AIEnrichmentRunRow) => outputCell(row, column),
        })),
    ]

    if (hasErrorRows) {
        columns.push({
            title: 'Error',
            key: 'error',
            render: (_, row) =>
                row.error ? (
                    <Tooltip title={row.error}>
                        <LemonTag type="danger">{summarizeError(row.error)}</LemonTag>
                    </Tooltip>
                ) : null,
        })
    }

    return columns
}

export function AIEnrichmentResultsTable(): JSX.Element {
    const { runRows, runSummary, runError, isRunning } = useValues(aiEnrichmentLogic)

    const columns = buildColumns(runRows)

    return (
        <div className="space-y-2">
            {runError && (
                <LemonBanner type="error">
                    <div>{summarizeError(runError)}</div>
                    <div className="text-xs mt-1 opacity-75">{runError}</div>
                </LemonBanner>
            )}
            <LemonTable
                dataSource={runRows}
                columns={columns}
                loading={isRunning && runRows.length === 0}
                rowKey={(row, index) => `${row.company}-${index}`}
                emptyState="Run the classifier to see verdicts here."
            />
            {runSummary && (
                <div className="text-secondary text-sm">
                    Classified {runSummary.classified} · Unknown {runSummary.unknown} · Errors {runSummary.errors}
                </div>
            )}
        </div>
    )
}
