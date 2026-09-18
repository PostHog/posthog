import { useActions, useValues } from 'kea'

import { LemonDivider, LemonInput, LemonSelect, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { HogFlowMinimalApi } from 'products/workflows/frontend/generated/api.schemas'

import { BroadcastStatus, broadcastsLogic, getBroadcastStatus } from './broadcastsLogic'

const STATUS_CONFIG: Record<BroadcastStatus, { label: string; type: LemonTagType }> = {
    draft: { label: 'Draft', type: 'default' },
    scheduled: { label: 'Scheduled', type: 'warning' },
    sending: { label: 'Sending', type: 'completion' },
    sent: { label: 'Sent', type: 'success' },
    archived: { label: 'Archived', type: 'muted' },
}

const METRIC_COLUMNS: { title: string; metricName: string }[] = [
    { title: 'Sent', metricName: 'email_sent' },
    { title: 'Delivered', metricName: 'email_delivered' },
    { title: 'Opened', metricName: 'email_opened' },
    { title: 'Clicked', metricName: 'email_link_clicked' },
    { title: 'Converted', metricName: 'conversion' },
]

export function BroadcastsTable(): JSX.Element {
    const { filteredBroadcasts, broadcastsLoading, hasLoadedBroadcasts, rowDetailsById, filters } =
        useValues(broadcastsLogic)
    const { archiveBroadcast, restoreBroadcast, duplicateBroadcast, deleteBroadcast, setFilters } =
        useActions(broadcastsLogic)

    const columns: LemonTableColumns<HogFlowMinimalApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, item) => (
                <LemonTableLink
                    to={urls.broadcast(item.id)}
                    title={item.name || 'Untitled broadcast'}
                    description={item.description}
                />
            ),
        },
        {
            title: 'Status',
            width: 0,
            render: (_, item) => {
                const config = STATUS_CONFIG[getBroadcastStatus(item, rowDetailsById[item.id])]
                return <LemonTag type={config.type}>{config.label}</LemonTag>
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
                if (!details) {
                    return <span className="text-muted">…</span>
                }
                return <span>{humanFriendlyNumber(details.totals[metricName] ?? 0)}</span>
            },
        })),
        createdByColumn() as LemonTableColumns<HogFlowMinimalApi>[number],
        createdAtColumn() as LemonTableColumns<HogFlowMinimalApi>[number],
        {
            key: 'actions',
            width: 0,
            render: (_, item) => (
                <More
                    overlay={
                        <>
                            <LemonButton
                                fullWidth
                                data-attr="broadcast-duplicate"
                                onClick={() => duplicateBroadcast(item)}
                            >
                                Duplicate
                            </LemonButton>
                            <LemonDivider />
                            <LemonButton
                                fullWidth
                                status={item.status === 'archived' ? 'default' : 'danger'}
                                data-attr="broadcast-archive-restore"
                                onClick={() =>
                                    item.status === 'archived' ? restoreBroadcast(item) : archiveBroadcast(item)
                                }
                            >
                                {item.status === 'archived' ? 'Restore' : 'Archive'}
                            </LemonButton>
                            {item.status === 'archived' && (
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    data-attr="broadcast-delete"
                                    onClick={() => deleteBroadcast(item)}
                                >
                                    Delete permanently
                                </LemonButton>
                            )}
                        </>
                    }
                />
            ),
        },
    ]

    const hasFilters = !!filters.search || !!filters.createdBy || filters.status !== 'all'
    const isEmpty = hasLoadedBroadcasts && !broadcastsLoading && filteredBroadcasts.length === 0 && !hasFilters

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
            <div className="mb-2 flex flex-wrap justify-between gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search for broadcasts"
                    onChange={(search) => setFilters({ search })}
                    value={filters.search}
                    data-attr="broadcasts-search"
                />
                <div className="flex flex-wrap items-center gap-2">
                    <span>
                        <b>Status</b>
                    </span>
                    <LemonSelect
                        dropdownMatchSelectWidth={false}
                        size="small"
                        value={filters.status}
                        onChange={(status) => setFilters({ status })}
                        data-attr="broadcasts-status-filter"
                        options={[
                            { label: 'All', value: 'all' as const },
                            { label: 'Draft', value: 'draft' as const },
                            { label: 'Scheduled', value: 'scheduled' as const },
                            { label: 'Sending', value: 'sending' as const },
                            { label: 'Sent', value: 'sent' as const },
                            { label: 'Archived', value: 'archived' as const },
                        ]}
                    />
                    <span className="ml-1">
                        <b>Created by</b>
                    </span>
                    <MemberSelect
                        value={filters.createdBy}
                        onChange={(user) => setFilters({ createdBy: user?.uuid || null })}
                    />
                </div>
            </div>
            <LemonTable
                dataSource={filteredBroadcasts}
                loading={broadcastsLoading}
                rowKey="id"
                columns={columns}
                nouns={['broadcast', 'broadcasts']}
                emptyState={hasFilters ? 'No broadcasts match these filters' : 'No broadcasts'}
                data-attr="broadcasts-table"
            />
        </div>
    )
}
