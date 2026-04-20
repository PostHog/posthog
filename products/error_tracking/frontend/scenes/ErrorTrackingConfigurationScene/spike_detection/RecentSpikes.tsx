import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { urls } from 'scenes/urls'

import { SpikeEventOrder, recentSpikesLogic } from './recentSpikesLogic'

function orderToSorting(order: SpikeEventOrder): Sorting {
    if (order.startsWith('-')) {
        return { columnKey: order.slice(1), order: -1 }
    }
    return { columnKey: order, order: 1 }
}

function sortingToOrder(sorting: Sorting): SpikeEventOrder {
    const prefix = sorting.order === -1 ? '-' : ''
    return `${prefix}${sorting.columnKey}` as SpikeEventOrder
}

export function RecentSpikes(): JSX.Element {
    const { recentSpikes, spikesResponseLoading, pagination, order } = useValues(recentSpikesLogic)
    const { setOrder } = recentSpikesLogic.actions

    const columns: LemonTableColumns<ErrorTrackingSpikeEvent> = [
        {
            title: 'Issue',
            key: 'issue',
            render: (_, record) => (
                <Link to={urls.errorTrackingIssue(record.issue.id)}>{record.issue.name || 'Unknown issue'}</Link>
            ),
        },
        {
            title: 'Detected at',
            dataIndex: 'detected_at',
            sorter: true,
            render: (_, record) => <TZLabel time={record.detected_at} />,
        },
        {
            title: 'Baseline',
            dataIndex: 'computed_baseline',
            sorter: true,
            render: (_, record) => <span>{Math.round(record.computed_baseline)}</span>,
        },
        {
            title: 'Multiplier',
            dataIndex: 'current_bucket_value',
            sorter: true,
            render: (_, record) => {
                const multiplier =
                    record.computed_baseline > 0
                        ? Math.round(record.current_bucket_value / record.computed_baseline)
                        : record.current_bucket_value
                return <span>{multiplier}x</span>
            },
        },
    ]

    return (
        <LemonTable<ErrorTrackingSpikeEvent>
            dataSource={recentSpikes}
            columns={columns}
            loading={spikesResponseLoading}
            pagination={pagination}
            sorting={orderToSorting(order)}
            onSort={(newSorting) => {
                if (newSorting) {
                    setOrder(sortingToOrder(newSorting))
                }
            }}
            noSortingCancellation
            useURLForSorting={false}
            emptyState={!spikesResponseLoading ? 'No spike events detected yet.' : undefined}
        />
    )
}
