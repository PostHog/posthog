import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { HogFlowMinimalApi } from 'products/workflows/frontend/generated/api.schemas'

import {
    BROADCASTS_PAGE_SIZE,
    BroadcastsStatusFilter,
    broadcastsLogic,
    getBroadcastStatus,
    isEligibleWorkflow,
} from './broadcastsLogic'
import { BroadcastStatusTag } from './BroadcastStatusTag'

const METRIC_COLUMNS: { title: string; metricName: string }[] = [
    { title: 'Sent', metricName: 'email_sent' },
    { title: 'Delivered', metricName: 'email_delivered' },
    { title: 'Opened', metricName: 'email_opened' },
    { title: 'Clicked', metricName: 'email_link_clicked' },
    { title: 'Converted', metricName: 'conversion' },
]

export function BroadcastsTable(): JSX.Element {
    const { broadcasts, broadcastsLoading, hasLoadedBroadcasts, rowDetailsById, filters, filtersPending, loadFailed } =
        useValues(broadcastsLogic)
    // Rows from other filters stay behind the loading state, and are dropped once the load for these fails.
    const hideRows = loadFailed && filtersPending
    const { setFilters } = useActions(broadcastsLogic)
    const { page } = filters
    const isFiltered = !!filters.search || filters.status !== 'all' || !!filters.createdBy

    const columns: LemonTableColumns<HogFlowMinimalApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, item) => (
                <div className="flex items-center gap-2">
                    <LemonTableLink
                        to={urls.broadcast(item.id)}
                        title={item.name || 'Untitled broadcast'}
                        description={item.description}
                    />
                    {isEligibleWorkflow(item) && (
                        <LemonTag
                            type="muted"
                            data-attr="broadcast-workflow-tag"
                            title="A workflow with a batch trigger and one email, shown here as a broadcast."
                        >
                            Workflow
                        </LemonTag>
                    )}
                </div>
            ),
        },
        {
            title: 'Status',
            width: 0,
            render: (_, item) => {
                return <BroadcastStatusTag status={getBroadcastStatus(item, rowDetailsById[item.id])} />
            },
        },
        ...METRIC_COLUMNS.map(({ title, metricName }) => ({
            title,
            width: 0,
            align: 'right' as const,
            render: (_: unknown, item: HogFlowMinimalApi) => {
                const details = rowDetailsById[item.id]
                if (item.status === 'draft') {
                    return <span className="text-muted">-</span>
                }
                if (!details?.totals) {
                    return <span className="text-muted">…</span>
                }
                return <span>{humanFriendlyNumber(details.totals[metricName] ?? 0)}</span>
            },
        })),
        createdByColumn() as LemonTableColumns<HogFlowMinimalApi>[number],
        createdAtColumn() as LemonTableColumns<HogFlowMinimalApi>[number],
    ]

    const isEmpty =
        hasLoadedBroadcasts &&
        !broadcastsLoading &&
        !filtersPending &&
        !loadFailed &&
        !isFiltered &&
        broadcasts.count === 0

    if (isEmpty) {
        return (
            <div
                className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border py-12"
                data-attr="broadcasts-empty-state"
            >
                <h3 className="m-0 text-lg font-semibold">No broadcasts yet</h3>
                <p className="m-0 text-secondary">Send a one-time or scheduled email to an audience of your users.</p>
                <LemonButton type="primary" to={urls.broadcastNew()} data-attr="broadcasts-empty-new">
                    New broadcast
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search broadcasts"
                    onChange={(search) => setFilters({ search })}
                    value={filters.search}
                    // The API rejects longer search terms.
                    maxLength={200}
                    data-attr="broadcasts-search"
                />
                <div className="flex flex-wrap items-center gap-2">
                    <b>Status</b>
                    <LemonSelect
                        dropdownMatchSelectWidth={false}
                        size="small"
                        onChange={(status) => setFilters({ status: status as BroadcastsStatusFilter })}
                        options={[
                            { label: 'All', value: 'all' },
                            { label: 'Active', value: 'active' },
                            { label: 'Draft', value: 'draft' },
                            { label: 'Archived', value: 'archived' },
                        ]}
                        value={filters.status}
                        data-attr="broadcasts-status-filter"
                    />
                    <b className="ml-1">Created by</b>
                    <MemberSelect
                        value={filters.createdBy}
                        onChange={(user) => setFilters({ createdBy: user?.uuid || null })}
                    />
                </div>
            </div>
            <LemonTable
                dataSource={hideRows ? [] : broadcasts.results}
                pagination={{
                    controlled: true,
                    pageSize: BROADCASTS_PAGE_SIZE,
                    currentPage: page,
                    entryCount: broadcasts.count,
                    onForward: broadcasts.next ? () => setFilters({ page: page + 1 }) : undefined,
                    onBackward: page > 1 ? () => setFilters({ page: page - 1 }) : undefined,
                }}
                loading={broadcastsLoading || (filtersPending && !loadFailed)}
                rowKey="id"
                columns={columns}
                nouns={['broadcast', 'broadcasts']}
                emptyState={
                    loadFailed
                        ? "Couldn't load broadcasts. Refresh the page to try again."
                        : isFiltered
                          ? 'No broadcasts match these filters'
                          : 'No broadcasts'
                }
                data-attr="broadcasts-table"
            />
        </div>
    )
}
