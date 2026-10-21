import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconLetter, IconNotification } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

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
    // A step deleted from the workflow still has metrics in the range, but no step to open.
    removed?: boolean
}

const METRIC_OPTIONS: { value: LeaderboardMetric; label: string }[] = [
    { value: 'sent', label: 'Sent' },
    { value: 'opened', label: 'Opened' },
    { value: 'clicked', label: 'Clicked' },
]

export function WorkflowMessageLeaderboard({
    id,
    logicKey,
    appSourceId,
}: {
    id: string
    logicKey: string
    appSourceId?: string
}): JSX.Element {
    const summaryLogic = workflowMetricsSummaryLogic({ logicKey, id, overview: true, appSourceId })
    const {
        emailMetricsRows,
        pushMetricsRows,
        emailTotalsByActionIdLoading,
        pushTotalsByActionIdLoading,
        params,
        messageTotalsFailed,
        emailTotalsByActionId,
        pushTotalsByActionId,
    } = useValues(summaryLogic)
    const { loadEmailTotals, loadPushTotals } = useActions(summaryLogic)
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
        const known = new Set(all.map((row) => row.id))
        for (const [actionId, totals] of Object.entries(emailTotalsByActionId)) {
            const emailActivity =
                (totals.email_sent ?? 0) + (totals.email_opened ?? 0) + (totals.email_link_clicked ?? 0)
            if (!known.has(actionId) && emailActivity > 0) {
                const sent = totals.email_sent ?? 0
                all.push({
                    id: actionId,
                    name: 'Removed email',
                    channel: 'email',
                    sent,
                    opened: totals.email_opened ?? 0,
                    clicked: totals.email_link_clicked ?? 0,
                    engagementBase: Math.max(0, sent - (totals.email_untracked ?? 0)),
                    removed: true,
                })
            }
        }
        for (const [actionId, totals] of Object.entries(pushTotalsByActionId)) {
            if (!known.has(actionId) && (totals.push_sent ?? 0) + (totals.push_opened ?? 0) > 0) {
                all.push({
                    id: actionId,
                    name: 'Removed push notification',
                    channel: 'push',
                    sent: totals.push_sent ?? 0,
                    opened: totals.push_opened ?? 0,
                    clicked: null,
                    engagementBase: totals.push_sent ?? 0,
                    removed: true,
                })
            }
        }
        return all.filter((row) => row[metric] !== null).sort((a, b) => (b[metric] ?? 0) - (a[metric] ?? 0))
    }, [emailMetricsRows, pushMetricsRows, emailTotalsByActionId, pushTotalsByActionId, metric])

    const columns: LemonTableColumns<LeaderboardRow> = [
        {
            key: 'rank',
            width: 0,
            render: (_, __, index) => <span className="text-muted">{index + 1}</span>,
        },
        {
            title: 'Message',
            key: 'name',
            render: (_, row) => {
                const label = (
                    <>
                        <span className="flex text-base text-secondary">
                            {row.channel === 'email' ? <IconLetter /> : <IconNotification />}
                        </span>
                        <span>{row.name}</span>
                    </>
                )
                return row.removed ? (
                    <span className="inline-flex items-center gap-1.5 font-medium text-muted">{label}</span>
                ) : (
                    <Link
                        to={metricsStepUrl(id, row.id, params, appSourceId)}
                        className="inline-flex items-center gap-1.5 font-medium"
                        data-attr="workflow-overview-leaderboard-message"
                    >
                        {label}
                    </Link>
                )
            },
        },
        {
            title: METRIC_OPTIONS.find((o) => o.value === metric)?.label,
            key: 'value',
            align: 'right',
            render: (_, row) => {
                const value = row[metric] ?? 0
                return (
                    <span className="whitespace-nowrap">
                        <span translate="no">{humanFriendlyNumber(value)}</span>
                        {metric !== 'sent' ? (
                            <span className="text-muted" translate="no">
                                {` (${row.engagementBase > 0 ? percentage(value / row.engagementBase, 1) : '-'})`}
                            </span>
                        ) : null}
                    </span>
                )
            },
        },
    ]

    const loading = emailTotalsByActionIdLoading || pushTotalsByActionIdLoading
    const hasMessages = rows.length > 0 || emailMetricsRows.length > 0 || pushMetricsRows.length > 0

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
            {messageTotalsFailed ? (
                <span className="flex flex-wrap items-center gap-2 text-sm text-muted">
                    Couldn't load message counts.
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => {
                            loadEmailTotals({})
                            loadPushTotals({})
                        }}
                        loading={loading}
                        data-attr="workflow-overview-leaderboard-retry"
                    >
                        Try again
                    </LemonButton>
                </span>
            ) : !loading && !hasMessages ? (
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
