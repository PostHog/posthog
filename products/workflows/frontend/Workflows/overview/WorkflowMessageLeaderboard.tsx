import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconLetter, IconNotification } from '@posthog/icons'
import { LemonSegmentedButton, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { metricsStepUrl } from '../metricsDrillParams'
import { workflowMetricsSummaryLogic } from '../workflowMetricsSummaryLogic'

type LeaderboardMetric = 'sent' | 'opened' | 'clicked'

type LeaderboardRow = {
    id: string
    name: string
    channel: 'email' | 'push'
    sent: number
    opened: number
    // Push has no link tracking, so it drops out of the clicked ranking instead of ranking as zero.
    clicked: number | null
    // Opens and clicks only happen on tracked sends, so rates read against this, not `sent`.
    engagementBase: number
}

const METRIC_OPTIONS: { value: LeaderboardMetric; label: string }[] = [
    { value: 'sent', label: 'Sent' },
    { value: 'opened', label: 'Opened' },
    { value: 'clicked', label: 'Clicked' },
]

export function WorkflowMessageLeaderboard({ id, logicKey }: { id: string; logicKey: string }): JSX.Element {
    const { emailMetricsRows, pushMetricsRows, emailTotalsByActionIdLoading, pushTotalsByActionIdLoading, params } =
        useValues(workflowMetricsSummaryLogic({ logicKey, id }))
    const [metric, setMetric] = useState<LeaderboardMetric>('sent')

    const rows = useMemo<LeaderboardRow[]>(() => {
        const all: LeaderboardRow[] = [
            ...emailMetricsRows.map((row) => ({
                id: row.id,
                name: row.email,
                channel: 'email' as const,
                sent: row.sent,
                opened: row.opened,
                clicked: row.linkClicked,
                engagementBase: row.trackedSends,
            })),
            ...pushMetricsRows.map((row) => ({
                id: row.id,
                name: row.push,
                channel: 'push' as const,
                sent: row.sent,
                opened: row.opened,
                clicked: null,
                engagementBase: row.sent,
            })),
        ]
        return all.filter((row) => row[metric] !== null).sort((a, b) => (b[metric] ?? 0) - (a[metric] ?? 0))
    }, [emailMetricsRows, pushMetricsRows, metric])

    const columns: LemonTableColumns<LeaderboardRow> = [
        {
            key: 'rank',
            width: 0,
            render: (_, __, index) => <span className="text-muted">{index + 1}</span>,
        },
        {
            title: 'Message',
            key: 'name',
            render: (_, row) => (
                <Link
                    to={metricsStepUrl(id, row.id, params)}
                    className="inline-flex items-center gap-1.5 font-medium"
                    data-attr="workflow-overview-leaderboard-message"
                >
                    <span className="flex text-base text-secondary">
                        {row.channel === 'email' ? <IconLetter /> : <IconNotification />}
                    </span>
                    {row.name}
                </Link>
            ),
        },
        {
            title: METRIC_OPTIONS.find((o) => o.value === metric)?.label,
            key: 'value',
            align: 'right',
            render: (_, row) => {
                const value = row[metric] ?? 0
                return (
                    <span className="whitespace-nowrap">
                        {humanFriendlyNumber(value)}
                        {metric !== 'sent' ? (
                            <span className="text-muted">
                                {' '}
                                ({row.engagementBase > 0 ? percentage(value / row.engagementBase, 1) : '-'})
                            </span>
                        ) : null}
                    </span>
                )
            },
        },
    ]

    const loading = emailTotalsByActionIdLoading || pushTotalsByActionIdLoading
    const hasMessages = emailMetricsRows.length > 0 || pushMetricsRows.length > 0

    return (
        <div
            className="flex flex-col gap-3 rounded border bg-surface-primary p-4"
            data-attr="workflow-overview-leaderboard"
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="mb-0 text-base font-semibold">Message leaderboard</h3>
                {hasMessages ? (
                    <LemonSegmentedButton
                        size="xsmall"
                        value={metric}
                        onChange={setMetric}
                        options={METRIC_OPTIONS}
                        data-attr="workflow-overview-leaderboard-metric"
                    />
                ) : null}
            </div>
            {!loading && !hasMessages ? (
                <span className="text-sm text-muted">This workflow has no email or push steps yet.</span>
            ) : (
                <LemonTable
                    columns={columns}
                    dataSource={rows}
                    loading={loading}
                    rowKey="id"
                    size="small"
                    embedded
                    emptyState="No push steps track clicks. Pick Sent or Opened to rank them."
                />
            )}
        </div>
    )
}
