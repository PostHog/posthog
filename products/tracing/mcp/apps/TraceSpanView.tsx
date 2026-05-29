import type { ReactElement } from 'react'

import { DescriptionList } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

export interface TraceSpanData {
    uuid: string
    trace_id: string
    span_id: string
    parent_span_id?: string | null
    name: string
    kind?: string | null
    service_name?: string | null
    status_code?: number | null
    timestamp: string
    end_time?: string | null
    duration_nano?: number | null
    is_root_span?: boolean
    matched_filter?: boolean
    _posthogUrl?: string
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
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            fractionalSecondDigits: 3,
        })
    } catch {
        return ts
    }
}

const statusVariant: Record<string, 'success' | 'destructive' | 'warning' | 'default'> = {
    '0': 'default',
    '1': 'success',
    '2': 'destructive',
}

const statusLabel: Record<string, string> = {
    '0': 'Unset',
    '1': 'OK',
    '2': 'Error',
}

const kindLabel: Record<string, string> = {
    '0': 'Unspecified',
    '1': 'Internal',
    '2': 'Server',
    '3': 'Client',
    '4': 'Producer',
    '5': 'Consumer',
}

export function TraceSpanView({ data }: { data: TraceSpanData }): ReactElement {
    const statusKey = String(data.status_code ?? '0')

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold break-all">{data.name}</span>
                        <Badge variant={statusVariant[statusKey] ?? 'default'}>
                            {statusLabel[statusKey] ?? `Status ${statusKey}`}
                        </Badge>
                        {data.is_root_span && <Badge>Root</Badge>}
                    </div>
                    {data.service_name && <span className="text-sm text-muted-foreground">{data.service_name}</span>}
                </div>

                <Card>
                    <CardContent>
                        <DescriptionList
                            columns={2}
                            items={[
                                { label: 'Trace ID', value: data.trace_id },
                                { label: 'Span ID', value: data.span_id },
                                ...(data.parent_span_id
                                    ? [{ label: 'Parent span ID', value: data.parent_span_id }]
                                    : []),
                                ...(data.kind != null
                                    ? [{ label: 'Kind', value: kindLabel[String(data.kind)] ?? String(data.kind) }]
                                    : []),
                                { label: 'Timestamp', value: formatTimestamp(data.timestamp) },
                                ...(data.duration_nano != null
                                    ? [{ label: 'Duration', value: formatDuration(data.duration_nano) }]
                                    : []),
                            ]}
                        />
                    </CardContent>
                </Card>
            </div>
        </div>
    )
}
