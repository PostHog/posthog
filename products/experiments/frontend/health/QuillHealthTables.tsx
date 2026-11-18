import { useValues } from 'kea'
import { useState } from 'react'

import { Button, Card, DataTable, Progress } from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { QuillVariantTag } from 'scenes/experiments/ExperimentView/QuillVariantTag'

import { FeatureFlagReleaseConditionsChange } from 'products/feature_flags/frontend/FeatureFlagReleaseConditionsChange'

import type { HealthRowCell, HealthRowsRow, HealthRowsTable } from './healthCheckRows'
import { type HealthSplitRow, formatHealthPercentage } from './healthCheckValues'

function QuillCell({ cell }: { cell: HealthRowCell | undefined }): JSX.Element | null {
    if (!cell) {
        return null
    }
    if ('variant' in cell) {
        return <QuillVariantTag variantKey={cell.variant} />
    }
    if ('time' in cell) {
        return <TZLabel time={cell.time} formatDate="MMMM D, YYYY" formatTime="h:mm A" />
    }
    // A release condition change lists one condition set per line.
    return <span className="whitespace-pre-line tabular-nums">{cell.text}</span>
}

export function QuillHealthCheckRowsTable({ table }: { table: HealthRowsTable }): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const flagId = String(experiment.feature_flag?.id ?? '')
    const expands = table.rows.some((row) => row.conditionsChange)
    const [openIndex, setOpenIndex] = useState<number | null>(null)
    const openRow = openIndex !== null ? table.rows[openIndex] : null

    const columns: DataTableProps<HealthRowsRow, unknown>['columns'] = [
        ...table.columns.map((column) => ({
            id: column.key,
            header: column.title,
            enableSorting: false,
            meta: { align: column.align },
            cell: ({ row: { original } }: { row: { original: HealthRowsRow } }) => (
                <QuillCell cell={original.cells[column.key]} />
            ),
        })),
        ...(expands
            ? [
                  {
                      id: 'change',
                      header: '',
                      enableSorting: false,
                      cell: ({ row }: { row: { index: number; original: HealthRowsRow } }) =>
                          row.original.conditionsChange ? (
                              <Button
                                  size="xs"
                                  aria-expanded={openIndex === row.index}
                                  onClick={() => setOpenIndex(openIndex === row.index ? null : row.index)}
                              >
                                  {openIndex === row.index ? 'Hide change' : 'Show change'}
                              </Button>
                          ) : null,
                  },
              ]
            : []),
    ]

    return (
        <div className="flex max-w-xl flex-col gap-2">
            <Card size="sm" flush className="pt-0">
                <DataTable
                    columns={columns}
                    data={table.rows}
                    fullWidth
                    size="sm"
                    getRowId={(_, index) => String(index)}
                    data-attr="experiment-health-check-rows"
                />
            </Card>
            {openRow?.conditionsChange && (
                <FeatureFlagReleaseConditionsChange
                    flagId={flagId}
                    // The diff keys its logic on this, so it must differ from the flag history's keys and between the saves of one flag.
                    activityId={`experiment-health-${openRow.conditionsChange.changedAt}`}
                    before={openRow.conditionsChange.before}
                    after={openRow.conditionsChange.after}
                />
            )}
        </div>
    )
}

export function QuillHealthExposureSplitTable({ rows, units }: { rows: HealthSplitRow[]; units: string }): JSX.Element {
    const hasPlan = rows.some((row) => row.plannedPercentage !== null)

    const columns: DataTableProps<HealthSplitRow, unknown>['columns'] = [
        {
            id: 'variant',
            header: 'Variant',
            enableSorting: false,
            cell: ({ row: { original } }) => <QuillVariantTag variantKey={original.variant} />,
        },
        {
            id: 'exposed',
            header: capitalizeFirstLetter(units),
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row: { original } }) => (
                <span className="tabular-nums">{humanFriendlyNumber(original.exposedCount)}</span>
            ),
        },
        {
            id: 'share',
            header: 'Share',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row: { original } }) => (
                <span className="flex items-center gap-2">
                    <Progress value={original.exposedPercentage} className="w-16 shrink-0" aria-label="Share" />
                    <span className="tabular-nums">{formatHealthPercentage(original.exposedPercentage)}</span>
                </span>
            ),
        },
        ...(hasPlan
            ? [
                  {
                      id: 'planned',
                      header: 'Planned',
                      enableSorting: false,
                      meta: { align: 'right' as const },
                      cell: ({ row: { original } }: { row: { original: HealthSplitRow } }) => (
                          <span className="tabular-nums">
                              {original.plannedPercentage === null
                                  ? null
                                  : formatHealthPercentage(original.plannedPercentage)}
                          </span>
                      ),
                  },
              ]
            : []),
    ]

    return (
        <Card size="sm" flush className="max-w-xl pt-0">
            <DataTable
                columns={columns}
                data={rows}
                fullWidth
                size="sm"
                getRowId={(row) => row.variant}
                data-attr="experiment-health-split"
            />
        </Card>
    )
}
