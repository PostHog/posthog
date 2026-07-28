import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { ScoreLabRunRow, scoreLabLogic } from './scoreLabLogic'
import { OutputColumnSpec, deriveOutputColumns } from './scoreLabResultColumns'

function outputCell(row: ScoreLabRunRow, column: OutputColumnSpec): JSX.Element | string | null {
    if (row.outputs === null) {
        return <span className="text-secondary">–</span>
    }
    const value = row.outputs[column.key]
    if (value === undefined) {
        return <span className="text-secondary">–</span>
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

function buildOutputColumns(rows: ScoreLabRunRow[]): LemonTableColumns<ScoreLabRunRow> {
    const outputColumns = deriveOutputColumns(rows)
    const hasErrorRows = rows.some((row) => row.outputs === null)

    const columns: LemonTableColumns<ScoreLabRunRow> = [
        { title: 'Company', key: 'company', dataIndex: 'company' },
        {
            title: 'Domain',
            key: 'domain',
            render: (_, row) => row.domain ?? <span className="text-secondary">–</span>,
        },
        ...outputColumns.map((column) => ({
            title: columnTitle(column.key),
            key: column.key,
            align: column.type === 'number' ? ('right' as const) : undefined,
            render: (_: unknown, row: ScoreLabRunRow) => outputCell(row, column),
        })),
    ]

    if (hasErrorRows) {
        columns.push({
            title: 'Error',
            key: 'error',
            render: (_, row) => (row.error ? <LemonTag type="danger">{row.error}</LemonTag> : null),
        })
    }

    return columns
}

export function ScoreLabResultsTable(): JSX.Element {
    const { runRows, runSummary, isRunning } = useValues(scoreLabLogic)

    const columns = buildOutputColumns(runRows)

    return (
        <div className="space-y-2">
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
