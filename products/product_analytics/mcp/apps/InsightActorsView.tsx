import { type ReactElement, type ReactNode, useMemo } from 'react'

import { DataTable, type DataTableColumn } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

import { type ActorRow, type InsightActorsData, isRetentionActorsData, toActorRows } from './insightActorsTransforms'
import { RetentionActorsView } from './RetentionActorsView'

export type { InsightActorsData }

interface InsightActorsViewProps {
    data: InsightActorsData
    openLink: (url: string) => void
}

export function InsightActorsView({ data, openLink }: InsightActorsViewProps): ReactElement {
    // Retention actors have a per-interval grid shape (no event_count) — render the cohort table instead.
    if (isRetentionActorsData(data)) {
        return <RetentionActorsView data={data} />
    }
    return <EventCountActorsView data={data} openLink={openLink} />
}

function EventCountActorsView({ data, openLink }: InsightActorsViewProps): ReactElement {
    const rows = useMemo(() => toActorRows(data), [data])
    // Membership-based sources (stickiness, lifecycle) project only the actor — no event count and
    // no recordings — so drive both columns off the actual result columns rather than assume them.
    const hasEventCount = data.results.columns.includes('event_count')
    const hasRecordings = data.results.columns.includes('recordings')

    const columns = useMemo((): DataTableColumn<ActorRow>[] => {
        const cols: DataTableColumn<ActorRow>[] = [
            {
                key: 'name',
                header: 'Actor',
                render: (row): ReactNode => {
                    const displayName = row.email || row.name || row.distinct_id || 'Anonymous'
                    return (
                        <div className="flex flex-col">
                            <span className="font-medium">{displayName}</span>
                            {row.distinct_id && row.distinct_id !== displayName && (
                                <span className="text-xs text-muted-foreground">{row.distinct_id}</span>
                            )}
                        </div>
                    )
                },
            },
        ]

        if (hasEventCount) {
            cols.push({
                key: 'event_count',
                header: 'Event count',
                sortable: true,
                align: 'right',
                render: (row): ReactNode => <Badge>{row.event_count?.toLocaleString() ?? '—'}</Badge>,
            })
        }

        if (hasRecordings) {
            cols.push({
                key: 'recordings',
                header: 'Recordings',
                align: 'right',
                render: (row): ReactNode => {
                    if (row.recordings.length === 0) {
                        return <span className="text-muted-foreground">—</span>
                    }
                    return (
                        <div className="flex gap-1 justify-end flex-wrap">
                            {row.recordings.map((url, i) => (
                                <Button
                                    key={i}
                                    variant="link"
                                    size="xs"
                                    // eslint-disable-next-line react/forbid-elements
                                    render={
                                        <a
                                            href={url}
                                            onClick={(e) => {
                                                e.preventDefault()
                                                openLink(url)
                                            }}
                                        />
                                    }
                                >
                                    {i + 1}
                                </Button>
                            ))}
                        </div>
                    )
                },
            })
        }

        return cols
    }, [hasEventCount, hasRecordings, openLink])

    return (
        <div className="p-4">
            <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">
                        {rows.length} actor{rows.length === 1 ? '' : 's'}
                        {data.hasMore ? '+' : ''}
                    </span>
                </div>
                <DataTable<ActorRow>
                    columns={columns}
                    data={rows}
                    // Without an event count there's nothing to rank by — keep the query's actor order.
                    defaultSort={hasEventCount ? { key: 'event_count', direction: 'desc' } : undefined}
                    emptyMessage="No actors found for this data point"
                />
            </div>
        </div>
    )
}
