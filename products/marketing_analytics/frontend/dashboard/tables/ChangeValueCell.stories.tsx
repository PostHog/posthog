import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton, LemonMenu, LemonTable, LemonTextArea } from '@posthog/lemon-ui'

import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { compareByCurrent } from './breakdownTableColumn'
import { buildExportMenuItems, buildExportRows } from './breakdownTableExport'
import { ChangeValueCell } from './ChangeValueCell'
import { CONVERSION_VALUE_COLUMN, VISITORS_COLUMN } from './webStatsColumns'
import { WebStatsRow } from './webStatsRows'

const meta: Meta<typeof ChangeValueCell> = {
    title: 'Scenes-App/Marketing analytics/Dashboard/Change value cell',
    component: ChangeValueCell,
    args: { currency: CurrencyCode.USD, compare: true },
}
export default meta
type Story = StoryObj<typeof meta>

export const Number: Story = { args: { value: [150, 100] } }
export const Rate: Story = { args: { value: [0.1, 0.08], kind: 'percentage' } }
export const BounceRate: Story = { args: { value: [0.2, 0.3], kind: 'percentage', reverseColors: true } }
export const Duration: Story = { args: { value: [90, 60], kind: 'duration' } }
export const Currency: Story = { args: { value: [12.5, 10], kind: 'currency' } }
export const NegativeCurrency: Story = { args: { value: [-12.5, -10], kind: 'currency' } }
export const NoBaseline: Story = { args: { value: [0, null] } }
export const Unavailable: Story = { args: { value: null } }
export const RoundedFlat: Story = { args: { value: [0.10001, 0.1], kind: 'percentage' } }

const rows: WebStatsRow[] = [
    { breakdownValue: 'Direct', visitors: [10, 5] },
    { breakdownValue: 'Paid search', visitors: [20, 10], conversion_value: [125, 100] },
    { breakdownValue: 'Email', visitors: [5, 10], conversion_value: [-12.5, -10] },
    { breakdownValue: 'Referral', visitors: [0, null], conversion_value: [0, null] },
    { breakdownValue: 'Organic search', visitors: [30, 25] },
]
const columns = [CONVERSION_VALUE_COLUMN, VISITORS_COLUMN]

export const InteractiveTable: Story = {
    render: function Render(): JSX.Element {
        const [sorting, setSorting] = useState<Sorting | null>({ columnKey: 'conversion_value', order: 1 })
        const [pastedExport, setPastedExport] = useState('')

        return (
            // A 960 px scene keeps snapshots from shrinking the table to its minimum content width.
            <div className="flex w-[60rem] max-w-full flex-col gap-4">
                <LemonMenu
                    items={buildExportMenuItems(
                        () =>
                            buildExportRows({
                                columns,
                                rows,
                                breakdownLabel: 'Channel',
                                breakdownValue: (row) => row.breakdownValue,
                                compare: true,
                            }),
                        'marketing-breakdown',
                        true
                    )}
                >
                    <LemonButton type="secondary">Export</LemonButton>
                </LemonMenu>
                <LemonTable
                    rowKey="breakdownValue"
                    dataSource={rows}
                    useURLForSorting={false}
                    sorting={sorting}
                    onSort={setSorting}
                    noSortingCancellation
                    columns={[
                        { title: 'Channel', dataIndex: 'breakdownValue' },
                        ...columns.map((column) => ({
                            key: column.key,
                            title: column.title,
                            align: 'right' as const,
                            sorter: compareByCurrent(column, sorting?.order ?? 1),
                            render: (_: unknown, row: WebStatsRow) => (
                                <ChangeValueCell
                                    value={column.value(row)}
                                    kind={column.kind}
                                    currency={CurrencyCode.USD}
                                    compare
                                />
                            ),
                        })),
                    ]}
                />
                <LemonTextArea
                    aria-label="Paste exported rows"
                    placeholder="Paste exported rows here"
                    value={pastedExport}
                    onChange={setPastedExport}
                />
            </div>
        )
    },
}
