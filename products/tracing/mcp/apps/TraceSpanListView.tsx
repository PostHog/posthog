import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

import { TraceSpanView, type TraceSpanData } from './TraceSpanView'

export interface TraceSpanListData {
    results: TraceSpanData[]
    hasMore?: boolean
    _posthogUrl?: string
}

export interface TraceSpanListViewProps {
    data: TraceSpanListData
    onSpanClick?: (span: TraceSpanData) => Promise<TraceSpanData | null>
}

function formatDuration(nanos: number): string {
    if (nanos < 1_000_000) {
        return `${(nanos / 1_000).toFixed(1)} \u00b5s`
    }
    if (nanos < 1_000_000_000) {
        return `${(nanos / 1_000_000).toFixed(1)} ms`
    }
    return `${(nanos / 1_000_000_000).toFixed(2)} s`
}

function formatTimestamp(ts: string): string {
    try {
        const d = new Date(ts)
        return d.toLocaleString(undefined, {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            fractionalSecondDigits: 3,
        })
    } catch {
        return ts
    }
}

const statusVariant: Record<string, 'success' | 'destructive' | 'default'> = {
    '0': 'default',
    '1': 'success',
    '2': 'destructive',
}

const statusLabel: Record<string, string> = {
    '0': 'Unset',
    '1': 'OK',
    '2': 'Error',
}

export function TraceSpanListView({ data, onSpanClick }: TraceSpanListViewProps): ReactElement {
    return (
        <ListDetailView<TraceSpanData>
            onItemClick={onSpanClick}
            backLabel="All spans"
            getItemName={(span) => span.name}
            renderDetail={(span) => <TraceSpanView data={span} />}
            renderList={(handleClick) => {
                const columns: DataTableColumn<TraceSpanData>[] = [
                    {
                        key: 'name',
                        header: 'Name',
                        sortable: true,
                        render: (row): ReactNode =>
                            onSpanClick ? (
                                <Button
                                    variant="link"
                                    size="sm"
                                    onClick={() => handleClick(row)}
                                    className="h-auto px-0 text-left max-w-xs truncate"
                                >
                                    {row.name}
                                </Button>
                            ) : (
                                <span className="max-w-xs truncate block">{row.name}</span>
                            ),
                    },
                    {
                        key: 'service_name',
                        header: 'Service',
                        sortable: true,
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground">{row.service_name ?? '\u2014'}</span>
                        ),
                    },
                    {
                        key: 'status_code',
                        header: 'Status',
                        render: (row): ReactNode => {
                            const key = String(row.status_code ?? '0')
                            return <Badge variant={statusVariant[key] ?? 'default'}>{statusLabel[key] ?? key}</Badge>
                        },
                    },
                    {
                        key: 'duration_nano',
                        header: 'Duration',
                        sortable: true,
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground font-mono text-xs">
                                {row.duration_nano != null ? formatDuration(row.duration_nano) : '\u2014'}
                            </span>
                        ),
                    },
                    {
                        key: 'timestamp',
                        header: 'Time',
                        sortable: true,
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground text-xs">{formatTimestamp(row.timestamp)}</span>
                        ),
                    },
                ]

                return (
                    <div className="p-4">
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-muted-foreground">
                                    {data.results.length} span{data.results.length === 1 ? '' : 's'}
                                    {data.hasMore ? '+' : ''}
                                </span>
                            </div>
                            <DataTable<TraceSpanData>
                                columns={columns}
                                data={data.results}
                                pageSize={20}
                                defaultSort={{ key: 'timestamp', direction: 'desc' }}
                                emptyMessage="No trace spans found"
                            />
                        </div>
                    </div>
                )
            }}
        />
    )
}
