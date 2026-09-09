import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { isNullBreakdown, isOtherBreakdown } from 'scenes/insights/utils'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendsQuery, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { TrafficRow, trafficRows } from './trafficRows'

export function TrafficTable({
    query,
    engagement,
    breakdownLabel,
}: {
    query: TrendsQuery
    engagement: boolean
    breakdownLabel: string
}): JSX.Element {
    const logic = dataNodeLogic({
        query,
        key: `marketing-dashboard-traffic-table-${engagement ? 'engagement' : 'acquisition'}-${breakdownLabel}`,
    })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const rows = trafficRows(((response as TrendsQueryResponse | undefined)?.results ?? []) as TrendResult[])
    const labels = engagement ? ['Session duration', 'Bounce rate'] : ['Visitors', 'Sessions', 'Pageviews']
    const formatValue = (value: number | undefined, index: number): string =>
        value === undefined
            ? '-'
            : engagement
              ? index === 1
                  ? percentage(value, 1)
                  : `${humanFriendlyNumber(value, 1)}s`
              : humanFriendlyNumber(value)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex justify-end">
                <LemonButton type="secondary" size="small" loading={responseLoading} onClick={() => loadData()}>
                    Reload
                </LemonButton>
            </div>
            {responseError && <LemonBanner type="error">{responseError}</LemonBanner>}
            <LemonTable<TrafficRow>
                dataSource={responseLoading ? [] : rows}
                loading={responseLoading}
                rowKey="name"
                emptyState="No website traffic matches this date range and filter."
                columns={[
                    {
                        title: breakdownLabel,
                        key: 'name',
                        dataIndex: 'name',
                        render: (_, row) =>
                            isNullBreakdown(row.name) ? 'No value' : isOtherBreakdown(row.name) ? 'Other' : row.name,
                        sorter: (a, b) => a.name.localeCompare(b.name),
                    },
                    ...labels.map((title, index) => ({
                        title,
                        key: String(index),
                        align: 'right' as const,
                        sorter: (a: TrafficRow, b: TrafficRow) => (a.current[index] ?? 0) - (b.current[index] ?? 0),
                        render: (_: unknown, row: TrafficRow) => (
                            <div>
                                <div className="font-semibold tabular-nums">
                                    {formatValue(row.current[index], index)}
                                </div>
                                {query.compareFilter?.compare && (
                                    <div className="text-xs text-secondary">
                                        vs. {formatValue(row.previous[index], index)} prior
                                    </div>
                                )}
                            </div>
                        ),
                    })),
                ]}
            />
        </div>
    )
}
