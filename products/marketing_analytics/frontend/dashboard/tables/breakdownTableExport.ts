import { LemonMenuItem } from '@posthog/lemon-ui'

import { downloadTableDataAsCsv, exportTableData } from 'scenes/web-analytics/webAnalyticsExportUtils'

import { ExporterFormat } from '~/types'

import type { BreakdownTableColumn } from './breakdownTableColumn'

export interface ExportRowsOptions<Row> {
    columns: BreakdownTableColumn<Row>[]
    rows: Row[]
    breakdownLabel: string
    breakdownValue: (row: Row) => string
    compare: boolean
}

/** Rows as `string[][]` with the header first, which is the shape the shared export helpers take. */
export function buildExportRows<Row>({
    columns,
    rows,
    breakdownLabel,
    breakdownValue,
    compare,
}: ExportRowsOptions<Row>): string[][] {
    if (!rows.length) {
        return []
    }

    const format = (column: BreakdownTableColumn<Row>, value: number): string =>
        column.exportValue ? column.exportValue(value) : String(value)

    const header = [
        breakdownLabel,
        ...columns.flatMap((column) =>
            compare ? [`${column.exportLabel} (current)`, `${column.exportLabel} (previous)`] : [column.exportLabel]
        ),
    ]

    const body = rows.map((row) => [
        breakdownValue(row),
        ...columns.flatMap((column) => {
            const value = column.value(row)
            const current = value ? format(column, value[0]) : ''
            if (!compare) {
                return [current]
            }
            return [current, value && value[1] !== null ? format(column, value[1]) : '']
        }),
    ])

    return [header, ...body]
}

export function buildExportMenuItems(getRows: () => string[][], filename: string, hasRows: boolean): LemonMenuItem[] {
    const disabledReason = hasRows ? undefined : 'No data to export yet'
    return [
        {
            label: 'Download CSV',
            disabledReason,
            onClick: () => downloadTableDataAsCsv(getRows(), `${filename}.csv`),
        },
        {
            label: 'Copy as CSV',
            disabledReason,
            onClick: () => exportTableData(getRows(), ExporterFormat.CSV),
        },
        {
            // A real .xlsx needs the server exporter, which cannot re-run an in-memory table.
            // Tab-separated text pastes into Excel as columns, which is what people want here.
            label: 'Copy for Excel',
            disabledReason,
            onClick: () => exportTableData(getRows(), ExporterFormat.XLSX),
        },
    ]
}
