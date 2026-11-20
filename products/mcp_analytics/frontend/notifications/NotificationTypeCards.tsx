import type { ReactNode } from 'react'

import { LemonButton, LemonSkeleton, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

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

export interface NotificationSetup {
    enabled: boolean
    /** Where and when it sends, such as "Slack, #mcp-alerts". */
    summary: ReactNode
    editTo: string
    onToggle: (enabled: boolean) => void
    toggleLoading: boolean
    toggleDisabled?: boolean
}

export interface NotificationTypeRow {
    key: string
    icon: JSX.Element
    headline: string
    lead: string
    tag?: JSX.Element
    cadence?: NotificationCadence
    saved?: SavedNotificationCounts
    action?: JSX.Element
    preview?: JSX.Element
    setup?: NotificationSetup
    savedRows: JSX.Element[]
}

function NotificationTypeCard({ row }: { row: NotificationTypeRow }): JSX.Element {
    return (
        <div
            className="flex min-w-0 flex-col rounded border border-primary bg-surface-primary"
            data-attr={`mcp-analytics-notification-card-${row.key}`}
        >
            <div className="flex items-start gap-3 p-4 pb-3">
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
                </div>
            </div>
            {/* The body grows so every card's footer lines up across the row. */}
            <div className="flex flex-1 flex-col gap-3 px-4 pb-4">
                {row.preview}
                {row.savedRows.length > 0 && <div className="mt-auto divide-y rounded border">{row.savedRows}</div>}
            </div>
            {row.setup ? (
                <div className="flex items-center justify-between gap-2 border-t border-primary px-4 py-3">
                    <div className="flex min-w-0 flex-col items-start gap-1">
                        <LemonSwitch
                            checked={row.setup.enabled}
                            onChange={row.setup.onToggle}
                            loading={row.setup.toggleLoading}
                            disabled={row.setup.toggleDisabled}
                            label={row.setup.enabled ? 'On' : 'Paused'}
                            labelClassName="font-medium"
                            tooltip={row.setup.enabled ? 'Pause sending' : 'Resume sending'}
                            data-attr={`mcp-analytics-notification-toggle-${row.key}`}
                        />
                        <span className="text-xs text-muted">{row.setup.summary}</span>
                    </div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={row.setup.editTo}
                        data-attr={`mcp-analytics-notification-edit-${row.key}`}
                    >
                        Edit
                    </LemonButton>
                </div>
            ) : (
                <div className="flex justify-end border-t border-primary px-4 py-3">
                    {!row.saved ? <LemonSkeleton className="h-8 w-24" /> : row.action}
                </div>
            )}
        </div>
    )
}

export function NotificationTypeCards({ rows }: { rows: NotificationTypeRow[] }): JSX.Element {
    return (
        <div
            className="grid grid-cols-1 gap-3 @4xl:grid-cols-3 @2xl:grid-cols-2"
            data-attr="mcp-analytics-notification-types"
        >
            {rows.map((row) => (
                <NotificationTypeCard key={row.key} row={row} />
            ))}
        </div>
    )
}
