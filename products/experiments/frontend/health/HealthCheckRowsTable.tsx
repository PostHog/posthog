import { LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { VariantTag } from 'scenes/experiments/ExperimentView/VariantTag'

import type { HealthRowCell, HealthRowsTable } from './healthCheckRows'

function renderCell(cell: HealthRowCell | undefined): JSX.Element | null {
    if (!cell) {
        return null
    }
    if ('variant' in cell) {
        return <VariantTag variantKey={cell.variant} />
    }
    if ('time' in cell) {
        return <TZLabel time={cell.time} formatDate="MMMM D, YYYY" formatTime="h:mm A" />
    }
    // A release condition change lists one condition set per line.
    return <span className="tabular-nums whitespace-pre-line">{cell.text}</span>
}

export function HealthCheckRowsTable({ table }: { table: HealthRowsTable }): JSX.Element {
    return (
        <LemonTable
            size="small"
            className="max-w-xl"
            dataSource={table.rows}
            rowKey={(_, index) => index}
            data-attr="experiment-health-check-rows"
            columns={table.columns.map((column) => ({
                title: column.title,
                key: column.key,
                align: column.align,
                render: (_: unknown, row: Record<string, HealthRowCell>) => renderCell(row[column.key]),
            }))}
        />
    )
}
