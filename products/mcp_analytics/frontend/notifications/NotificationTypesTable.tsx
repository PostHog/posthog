import { useState } from 'react'

import { LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export type NotificationCadence = 'instant' | 'daily' | 'weekly'

const CADENCE_LABELS: Record<NotificationCadence, string> = {
    instant: 'Instant',
    daily: 'Daily',
    weekly: 'Weekly',
}

export interface SavedNotificationCounts {
    total: number
    enabled: number
    /** The list behind the counts was cut at its page limit, so both numbers are lower bounds. */
    truncated: boolean
}

export function countSaved(items: { enabled?: boolean | null }[], truncated: boolean): SavedNotificationCounts {
    return { total: items.length, enabled: items.filter((item) => item.enabled).length, truncated }
}

export interface NotificationTypeRow {
    key: string
    icon: JSX.Element
    headline: string
    lead: string
    tag?: JSX.Element
    cadence?: NotificationCadence
    /** Undefined until the list of configured notifications has loaded. */
    saved?: SavedNotificationCounts
    action?: JSX.Element
    preview?: JSX.Element
    savedRows: JSX.Element[]
}

export function statusLabel({ total, enabled, truncated }: SavedNotificationCounts): string {
    // A cut list cannot say a template has nothing: the match may sit past the page limit.
    if (truncated) {
        if (total === 0) {
            return 'Unknown'
        }
        return enabled > 0 ? `${enabled}+ on` : `${total}+ paused`
    }
    if (total === 0) {
        return 'Not set up'
    }
    if (enabled === total) {
        return total === 1 ? 'On' : `${total} on`
    }
    if (enabled === 0) {
        return total === 1 ? 'Paused' : `${total} paused`
    }
    return `${enabled} of ${total} on`
}

/**
 * Rows that already have something set up start expanded, so the active destinations are visible
 * without a click. When nothing is set up yet every row starts expanded instead, because the
 * details are the only way to judge what a notification would send. The user's own toggles then
 * take over.
 *
 * Below the `@2xl` container width the status column folds into the notification cell, so a scene
 * beside an open side panel keeps the action on screen instead of scrolling sideways.
 */
export function NotificationTypesTable({ rows }: { rows: NotificationTypeRow[] }): JSX.Element {
    const [expandedOverrides, setExpandedOverrides] = useState<Record<string, boolean>>({})
    const nothingSetUp = rows.every((row) => row.saved && row.saved.total === 0)

    return (
        <LemonTable
            dataSource={rows}
            rowKey="key"
            showHeader={false}
            data-attr="mcp-analytics-notification-types"
            columns={[
                {
                    title: 'Notification',
                    key: 'notification',
                    className: 'min-w-64',
                    render: (_, row) => (
                        <div className="flex items-center gap-3 py-1">
                            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-surface-secondary text-lg text-muted">
                                {row.icon}
                            </span>
                            <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-semibold">{row.headline}</span>
                                    {row.tag}
                                    {row.cadence && (
                                        <LemonTag type="muted" size="small">
                                            {CADENCE_LABELS[row.cadence]}
                                        </LemonTag>
                                    )}
                                </div>
                                <div className="text-xs text-muted">{row.lead}</div>
                                {row.saved && (
                                    <div className="mt-0.5 text-xs text-muted @2xl:hidden">
                                        {statusLabel(row.saved)}
                                    </div>
                                )}
                            </div>
                        </div>
                    ),
                },
                {
                    title: 'Status',
                    key: 'status',
                    width: 0,
                    className: '@max-2xl:hidden',
                    render: (_, row) =>
                        row.saved ? (
                            <span className={cn('whitespace-nowrap', row.saved.total === 0 && 'text-muted')}>
                                {statusLabel(row.saved)}
                            </span>
                        ) : (
                            <LemonSkeleton className="h-4 w-16" />
                        ),
                },
                {
                    key: 'action',
                    width: 0,
                    align: 'right',
                    render: (_, row) =>
                        !row.saved ? (
                            <LemonSkeleton className="h-8 w-24" />
                        ) : row.action ? (
                            <div className="flex justify-end whitespace-nowrap">{row.action}</div>
                        ) : null,
                },
            ]}
            expandable={{
                rowExpandable: (row) => !!row.preview || row.savedRows.length > 0,
                isRowExpanded: (row) => expandedOverrides[row.key] ?? (nothingSetUp || (row.saved?.total ?? 0) > 0),
                onRowExpand: (row) => setExpandedOverrides((current) => ({ ...current, [row.key]: true })),
                onRowCollapse: (row) => setExpandedOverrides((current) => ({ ...current, [row.key]: false })),
                // pl-13 lines the details up with the headline text: the 8px cell padding, the 32px icon
                // tile and the 12px gap before the text.
                expandedRowRender: (row) => (
                    <div className="flex max-w-2xl flex-col gap-3 py-3 pr-4 pl-13">
                        {row.preview}
                        {row.savedRows.length > 0 && <div className="divide-y rounded border">{row.savedRows}</div>}
                    </div>
                ),
            }}
        />
    )
}
