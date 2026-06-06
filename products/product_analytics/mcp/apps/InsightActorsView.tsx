import { type ReactElement, type ReactNode, useMemo } from 'react'

import { DataTable, type DataTableColumn } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

export interface InsightActorsData {
    query: Record<string, unknown>
    results: {
        columns: string[]
        results: (string | number | null | string[])[][]
    }
    hasMore: boolean
    offset: number
    _posthogUrl?: string
}

interface ActorRow {
    distinct_id: string | null
    email: string | null
    name: string | null
    event_count: number | null
    recordings: string[]
}

function toActorRows(data: InsightActorsData): ActorRow[] {
    const { columns, results } = data.results
    return results.map((row) => {
        const obj: Record<string, unknown> = {}
        columns.forEach((col, i) => {
            obj[col] = row[i]
        })
        return {
            distinct_id: (obj.distinct_id as string) ?? null,
            email: (obj.email as string) ?? null,
            name: (obj.name as string) ?? null,
            event_count: (obj.event_count as number) ?? null,
            recordings: Array.isArray(obj.recordings) ? (obj.recordings as string[]) : [],
        }
    })
}

interface InsightActorsViewProps {
    data: InsightActorsData
    openLink: (url: string) => void
}

export function InsightActorsView({ data, openLink }: InsightActorsViewProps): ReactElement {
    const rows = useMemo(() => toActorRows(data), [data])
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
            {
                key: 'event_count',
                header: 'Event count',
                sortable: true,
                align: 'right',
                render: (row): ReactNode => <Badge>{row.event_count?.toLocaleString() ?? '—'}</Badge>,
            },
        ]

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
    }, [hasRecordings, openLink])

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
                    defaultSort={{ key: 'event_count', direction: 'desc' }}
                    emptyMessage="No actors found for this data point"
                />
            </div>
        </div>
    )
}
