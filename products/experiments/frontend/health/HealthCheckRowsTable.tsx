import { useValues } from 'kea'

import { LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { VariantTag } from 'scenes/experiments/ExperimentView/VariantTag'

import { FeatureFlagReleaseConditionsChange } from 'products/feature_flags/frontend/FeatureFlagReleaseConditionsChange'

import type { HealthRowCell, HealthRowsRow, HealthRowsTable } from './healthCheckRows'

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
    const { experiment } = useValues(experimentLogic)
    const flagId = String(experiment.feature_flag?.id ?? '')
    const expands = table.rows.some((row) => row.conditionsChange)
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
                render: (_: unknown, row: HealthRowsRow) => renderCell(row.cells[column.key]),
            }))}
            expandable={
                expands
                    ? {
                          rowExpandable: (row) => !!row.conditionsChange,
                          expandedRowRender: (row) =>
                              row.conditionsChange && (
                                  <FeatureFlagReleaseConditionsChange
                                      flagId={flagId}
                                      // The diff keys its logic on this, so it must differ from the flag history's
                                      // keys and between the saves of one flag.
                                      activityId={`experiment-health-${row.conditionsChange.changedAt}`}
                                      before={row.conditionsChange.before}
                                      after={row.conditionsChange.after}
                                  />
                              ),
                      }
                    : undefined
            }
        />
    )
}
