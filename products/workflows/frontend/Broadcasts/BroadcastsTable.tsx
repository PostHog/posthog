import { useValues } from 'kea'

import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
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
    const { broadcasts, broadcastsLoading, hasLoadedBroadcasts, rowDetailsById } = useValues(broadcastsLogic)

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
    ]

    const isEmpty = hasLoadedBroadcasts && !broadcastsLoading && broadcasts.results.length === 0

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
        <LemonTable
            dataSource={broadcasts.results}
            loading={broadcastsLoading}
            rowKey="id"
            columns={columns}
            nouns={['broadcast', 'broadcasts']}
            emptyState="No broadcasts"
            data-attr="broadcasts-table"
        />
    )
}
