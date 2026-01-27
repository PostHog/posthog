import type { ReactElement } from 'react'
import type { ErrorListVisualizerProps, ErrorIssue } from './types'
import { formatNumber } from './utils'

function formatTimeAgo(dateStr: string | undefined): string {
    if (!dateStr) return '-'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function StatusBadge({ status }: { status: ErrorIssue['status'] }): ReactElement {
    const colors = {
        active: {
            bg: 'var(--color-background-danger, #fef2f2)',
            text: 'var(--color-text-danger, #dc2626)',
            border: 'var(--color-border-danger, #fecaca)',
        },
        resolved: {
            bg: 'var(--color-background-success, #f0fdf4)',
            text: 'var(--color-text-success, #16a34a)',
            border: 'var(--color-border-success, #bbf7d0)',
        },
        suppressed: {
            bg: 'var(--color-background-secondary, #f9fafb)',
            text: 'var(--color-text-secondary, #6b7280)',
            border: 'var(--color-border-secondary, #e5e7eb)',
        },
    }

    const style = colors[status || 'active']

    return (
        <span
            style={{
                display: 'inline-block',
                padding: '0.125rem 0.5rem',
                fontSize: '0.75rem',
                fontWeight: 500,
                borderRadius: 'var(--border-radius-sm, 0.25rem)',
                backgroundColor: style.bg,
                color: style.text,
                border: `1px solid ${style.border}`,
                textTransform: 'capitalize',
            }}
        >
            {status || 'active'}
        </span>
    )
}

function MiniSparkline({ data }: { data: number[] | undefined }): ReactElement | null {
    if (!data || data.length === 0) return null

    const max = Math.max(...data, 1)
    const width = 60
    const height = 20
    const barWidth = width / data.length - 1

    return (
        <svg width={width} height={height} style={{ display: 'block' }}>
            {data.map((value, i) => {
                const barHeight = (value / max) * height
                return (
                    <rect
                        key={i}
                        x={i * (barWidth + 1)}
                        y={height - barHeight}
                        width={barWidth}
                        height={barHeight}
                        fill="var(--posthog-chart-4, #dc2626)"
                        opacity={0.7}
                    />
                )
            })}
        </svg>
    )
}

function ErrorRow({ issue }: { issue: ErrorIssue }): ReactElement {
    return (
        <div
            style={{
                display: 'grid',
                gridTemplateColumns: '1fr auto auto auto auto',
                gap: '1rem',
                alignItems: 'center',
                padding: '0.75rem 0',
                borderBottom: '1px solid var(--color-border-primary, #e5e7eb)',
            }}
        >
            {/* Error name and description */}
            <div style={{ minWidth: 0 }}>
                <div
                    style={{
                        fontWeight: 500,
                        color: 'var(--color-text-primary, #101828)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                    }}
                    title={issue.name}
                >
                    {issue.name || 'Unknown Error'}
                </div>
                {issue.description && (
                    <div
                        style={{
                            fontSize: '0.8125rem',
                            color: 'var(--color-text-secondary, #6b7280)',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            marginTop: '0.125rem',
                        }}
                        title={issue.description}
                    >
                        {issue.description}
                    </div>
                )}
            </div>

            {/* Sparkline */}
            <div style={{ width: '60px' }}>
                <MiniSparkline data={issue.volume} />
            </div>

            {/* Occurrences */}
            <div style={{ textAlign: 'right', minWidth: '60px' }}>
                <div
                    style={{
                        fontWeight: 600,
                        color: 'var(--color-text-primary, #101828)',
                    }}
                >
                    {formatNumber(issue.occurrences || 0)}
                </div>
                <div
                    style={{
                        fontSize: '0.6875rem',
                        color: 'var(--color-text-secondary, #6b7280)',
                        textTransform: 'uppercase',
                    }}
                >
                    events
                </div>
            </div>

            {/* Users */}
            <div style={{ textAlign: 'right', minWidth: '50px' }}>
                <div
                    style={{
                        fontWeight: 600,
                        color: 'var(--color-text-primary, #101828)',
                    }}
                >
                    {formatNumber(issue.users || 0)}
                </div>
                <div
                    style={{
                        fontSize: '0.6875rem',
                        color: 'var(--color-text-secondary, #6b7280)',
                        textTransform: 'uppercase',
                    }}
                >
                    users
                </div>
            </div>

            {/* Status and last seen */}
            <div style={{ textAlign: 'right', minWidth: '80px' }}>
                <StatusBadge status={issue.status} />
                <div
                    style={{
                        fontSize: '0.6875rem',
                        color: 'var(--color-text-secondary, #6b7280)',
                        marginTop: '0.25rem',
                    }}
                >
                    {formatTimeAgo(issue.last_seen)}
                </div>
            </div>
        </div>
    )
}

export function ErrorListVisualizer({ issues }: ErrorListVisualizerProps): ReactElement {
    if (!issues || issues.length === 0) {
        return (
            <div
                style={{
                    padding: '2rem',
                    textAlign: 'center',
                    color: 'var(--color-text-secondary, #6b7280)',
                }}
            >
                No errors found
            </div>
        )
    }

    return (
        <div>
            {/* Header */}
            <div
                style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr auto auto auto auto',
                    gap: '1rem',
                    alignItems: 'center',
                    padding: '0.5rem 0',
                    borderBottom: '2px solid var(--color-border-primary, #e5e7eb)',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--color-text-secondary, #6b7280)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                }}
            >
                <div>Error</div>
                <div style={{ width: '60px' }}>Trend</div>
                <div style={{ textAlign: 'right', minWidth: '60px' }}>Events</div>
                <div style={{ textAlign: 'right', minWidth: '50px' }}>Users</div>
                <div style={{ textAlign: 'right', minWidth: '80px' }}>Status</div>
            </div>

            {/* Rows */}
            {issues.map((issue) => (
                <ErrorRow key={issue.id} issue={issue} />
            ))}

            {/* Summary */}
            <div
                style={{
                    marginTop: '1rem',
                    padding: '0.75rem',
                    backgroundColor: 'var(--color-background-secondary, #f9fafb)',
                    borderRadius: 'var(--border-radius-md, 0.375rem)',
                    fontSize: '0.8125rem',
                    color: 'var(--color-text-secondary, #6b7280)',
                }}
            >
                Showing {issues.length} error{issues.length !== 1 ? 's' : ''} •{' '}
                {formatNumber(issues.reduce((sum, i) => sum + (i.occurrences || 0), 0))} total occurrences
            </div>
        </div>
    )
}
