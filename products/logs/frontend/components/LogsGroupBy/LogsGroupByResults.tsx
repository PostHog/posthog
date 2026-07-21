import { useActions, useValues } from 'kea'

import { LemonTable } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import type { _LogsGroupByGroupApi, OrderGroupsByEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { logsGroupByLogic } from './logsGroupByLogic'

/**
 * The grouped results table for the group-by lens (behind the `logs-group-by` flag).
 *
 * Column choice is deliberate — each column maps to a triage job:
 *  - value:     which entity is this (identity, the pivot for drill-in)
 *  - logs:      which groups are noisiest (default ranking)
 *  - errors:    which groups are failing (the "show me what's broken" ranking)
 *  - last seen: is it still happening
 * Anything that doesn't serve triage or drill-in (timeline art, duration, first seen) is out.
 *
 * Ranking is server-side: the endpoint returns the top-N by one aggregate, so a column sort
 * click re-queries rather than reordering the (truncated) page client-side.
 */

const SORTABLE_COLUMNS: OrderGroupsByEnumApi[] = ['log_count', 'error_count', 'last_seen']

export function LogsGroupByResults({ id }: { id: string }): JSX.Element {
    const { groupByResponse, groupByResponseLoading, groupByError, groups, orderGroupsBy } = useValues(
        logsGroupByLogic({ id })
    )
    const { setOrderGroupsBy } = useActions(logsGroupByLogic({ id }))
    const { groupBy } = useValues(logsViewerConfigLogic({ id }))

    // The Group view with no key chosen: prompt for one instead of showing an empty table.
    // No query runs in this state (the logic's loader guards on a null key).
    if (!groupBy) {
        return (
            <div className="flex-1 min-h-0 flex items-center justify-center text-muted" data-attr="logs-group-by-empty">
                Pick an attribute to group by
            </div>
        )
    }

    const columns: LemonTableColumns<_LogsGroupByGroupApi> = [
        {
            title: groupBy.key,
            dataIndex: 'value',
            render: (_, row) => <span className="font-mono text-xs">{row.value}</span>,
        },
        {
            title: 'Logs',
            dataIndex: 'log_count',
            align: 'right',
            render: (_, row) => humanFriendlyNumber(row.log_count),
            sorter: true,
        },
        {
            title: 'Errors',
            dataIndex: 'error_count',
            align: 'right',
            render: (_, row) =>
                row.error_count > 0 ? (
                    <span className="text-danger font-semibold">{humanFriendlyNumber(row.error_count)}</span>
                ) : (
                    <span className="text-muted">0</span>
                ),
            sorter: true,
        },
        {
            title: 'Last seen',
            dataIndex: 'last_seen',
            render: (_, row) => <TZLabel time={row.last_seen} />,
            sorter: true,
        },
    ]

    const { total_groups, total_logs, truncated } = groupByResponse

    return (
        <div className="flex-1 min-h-0 overflow-auto" data-attr="logs-group-by-results">
            {!groupByResponseLoading && !groupByError && total_groups > 0 && (
                <div className="px-2 py-1 text-muted text-xs">
                    {truncated
                        ? `Top ${humanFriendlyNumber(groups.length)} of ${humanFriendlyNumber(total_groups)} groups`
                        : `${humanFriendlyNumber(total_groups)} groups`}{' '}
                    (based on {humanFriendlyNumber(total_logs)} logs)
                </div>
            )}
            <LemonTable
                columns={columns}
                dataSource={groups}
                loading={groupByResponseLoading}
                // Ranking is a server concern: reflect the active order and re-query on change.
                sorting={{ columnKey: orderGroupsBy, order: -1 }}
                onSort={(sorting) => {
                    const columnKey = sorting?.columnKey as OrderGroupsByEnumApi | undefined
                    if (columnKey && SORTABLE_COLUMNS.includes(columnKey)) {
                        setOrderGroupsBy(columnKey)
                    }
                }}
                emptyState={
                    groupByError
                        ? 'Grouping failed — try a shorter time range or narrower filters'
                        : 'No groups found for the current filters'
                }
                rowKey="value"
                size="small"
            />
        </div>
    )
}
