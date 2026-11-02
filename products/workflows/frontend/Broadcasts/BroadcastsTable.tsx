import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TagSelect } from 'lib/components/TagSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { HogFlowMinimalApi } from 'products/workflows/frontend/generated/api.schemas'

import { archiveDisabledReason, manageDisabledReason } from './broadcastLifecycle'
import { BroadcastsEmptyState } from './BroadcastsEmptyState'
import {
    BROADCASTS_PAGE_SIZE,
    BroadcastsStatusFilter,
    broadcastsLogic,
    getBroadcastChannel,
    getBroadcastStatus,
} from './broadcastsLogic'
import { BroadcastStatusTag } from './BroadcastStatusTag'

// Push has no delivery receipts or link tracking, so those columns stay empty for a push broadcast.
const METRIC_COLUMNS: { title: string; metricName: string; pushMetricName: string | null }[] = [
    { title: 'Sent', metricName: 'email_sent', pushMetricName: 'push_sent' },
    { title: 'Delivered', metricName: 'email_delivered', pushMetricName: null },
    { title: 'Opened', metricName: 'email_opened', pushMetricName: 'push_opened' },
    { title: 'Clicked', metricName: 'email_link_clicked', pushMetricName: null },
    { title: 'Converted', metricName: 'conversion', pushMetricName: 'conversion' },
]

export function BroadcastsTable(): JSX.Element {
    const {
        broadcasts,
        broadcastsLoading,
        hasLoadedBroadcasts,
        rowDetailsById,
        filters,
        filtersPending,
        loadFailed,
        tags: allTags,
        savingTagsFor,
    } = useValues(broadcastsLogic)
    // Rows from other filters stay behind the loading state, and are dropped once the load for these fails.
    const hideRows = loadFailed && filtersPending
    const { setFilters, archiveBroadcast, restoreBroadcast, deleteBroadcast, saveBroadcastTags } =
        useActions(broadcastsLogic)
    const { page } = filters
    const isFiltered = !!filters.search || filters.status !== 'all' || !!filters.createdBy || filters.tags.length > 0

    const columns: LemonTableColumns<HogFlowMinimalApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, item) => (
                <div className="flex items-center gap-2">
                    {item.status === 'archived' ? (
                        <Tooltip title="Restore this broadcast to make changes">
                            <span className="font-semibold text-sm text-muted">
                                {item.name || 'Untitled broadcast'}
                            </span>
                        </Tooltip>
                    ) : (
                        <LemonTableLink
                            to={urls.broadcast(item.id)}
                            title={item.name || 'Untitled broadcast'}
                            description={item.description}
                            truncateDescription
                        />
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
        {
            title: 'Tags',
            key: 'tags',
            width: 220,
            render: function Render(_, item) {
                const shown = {
                    tags: [...(item.tags ?? [])],
                    onTagClick: (tag: string) => {
                        if (!filters.tags.includes(tag)) {
                            setFilters({ tags: [...filters.tags, tag] })
                        }
                    },
                    wrap: true,
                    maxVisibleTags: 2,
                    'data-attr': 'broadcast-tags',
                }
                return manageDisabledReason(item.user_access_level) ? (
                    <ObjectTags {...shown} staticOnly />
                ) : (
                    <ObjectTags
                        {...shown}
                        onChange={(tags) => saveBroadcastTags(item.id, tags)}
                        saving={savingTagsFor === item.id}
                        tagsAvailable={allTags}
                    />
                )
            },
        },
        ...METRIC_COLUMNS.map(({ title, metricName, pushMetricName }) => ({
            title,
            width: 0,
            align: 'right' as const,
            render: (_: unknown, item: HogFlowMinimalApi) => {
                const details = rowDetailsById[item.id]
                const metric = getBroadcastChannel(item.actions as any) === 'push' ? pushMetricName : metricName
                if (item.status === 'draft' || !metric) {
                    return <span className="text-muted">-</span>
                }
                if (!details?.totals) {
                    return <span className="text-muted">…</span>
                }
                return <span>{humanFriendlyNumber(details.totals[metric] ?? 0)}</span>
            },
        })),
        createdByColumn() as LemonTableColumns<HogFlowMinimalApi>[number],
        createdAtColumn() as LemonTableColumns<HogFlowMinimalApi>[number],
        {
            width: 0,
            render: function Render(_, item) {
                const isArchived = item.status === 'archived'
                const accessReason = manageDisabledReason(item.user_access_level)
                return (
                    <More
                        overlay={
                            isArchived ? (
                                <>
                                    <LemonButton
                                        fullWidth
                                        onClick={() => restoreBroadcast(item)}
                                        disabledReason={accessReason}
                                        data-attr="broadcast-row-restore"
                                    >
                                        Restore as draft
                                    </LemonButton>
                                    <LemonButton
                                        fullWidth
                                        status="danger"
                                        onClick={() => deleteBroadcast(item)}
                                        disabledReason={accessReason}
                                        data-attr="broadcast-row-delete"
                                    >
                                        Delete
                                    </LemonButton>
                                </>
                            ) : (
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    onClick={() => archiveBroadcast(item)}
                                    disabledReason={
                                        accessReason ??
                                        archiveDisabledReason(rowDetailsById[item.id]?.batchJobStatuses ?? null)
                                    }
                                    data-attr="broadcast-row-archive"
                                >
                                    Archive
                                </LemonButton>
                            )
                        }
                    />
                )
            },
        },
    ]

    const isEmpty =
        hasLoadedBroadcasts &&
        !broadcastsLoading &&
        !filtersPending &&
        !loadFailed &&
        !isFiltered &&
        broadcasts.count === 0

    if (isEmpty) {
        return <BroadcastsEmptyState />
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
                            { label: 'Draft', value: 'draft' },
                            { label: 'Scheduled', value: 'scheduled' },
                            { label: 'Sending', value: 'sending' },
                            { label: 'Sent', value: 'sent' },
                            { label: 'Failed', value: 'failed' },
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
                    <b className="ml-1">Tags</b>
                    <TagSelect
                        size="small"
                        defaultLabel="Any tags"
                        value={filters.tags}
                        onChange={(tags) => setFilters({ tags })}
                        listDataAttr="broadcasts-tags-filter-list"
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
