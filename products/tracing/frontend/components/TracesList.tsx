import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { humanFriendlyMilliseconds } from 'lib/utils'

import type { TraceSummary } from '../data/mockTraceData'
import { statusTagType } from './tracingUtils'

interface TracesListProps {
    traces: TraceSummary[]
    selectedTraceId: string | null
    onSelectTrace: (traceId: string | null) => void
}

export function TracesList({ traces, selectedTraceId, onSelectTrace }: TracesListProps): JSX.Element {
    const columns: LemonTableColumns<TraceSummary> = [
        {
            title: 'Trace ID',
            dataIndex: 'trace_id',
            render: (_, trace) => (
                <span className="font-mono text-xs">
                    {trace.trace_id.slice(0, 8)}...{trace.trace_id.slice(-4)}
                </span>
            ),
        },
        {
            title: 'Root operation',
            dataIndex: 'root_span_name',
            render: (_, trace) => <span className="font-semibold">{trace.root_span_name}</span>,
        },
        {
            title: 'Service',
            dataIndex: 'root_service_name',
            render: (_, trace) => <LemonTag>{trace.root_service_name}</LemonTag>,
        },
        {
            title: 'Status',
            dataIndex: 'status_code',
            render: (_, trace) => (
                <LemonTag type={statusTagType(trace.status_code)}>{trace.status_code.toUpperCase()}</LemonTag>
            ),
        },
        {
            title: 'Spans',
            dataIndex: 'span_count',
            align: 'right',
        },
        {
            title: 'Duration',
            dataIndex: 'duration_ms',
            align: 'right',
            render: (_, trace) => (
                <span className="font-mono text-xs">{humanFriendlyMilliseconds(trace.duration_ms)}</span>
            ),
        },
        {
            title: 'Time',
            dataIndex: 'timestamp',
            render: (_, trace) => (
                <span className="text-muted text-xs whitespace-nowrap">
                    {new Date(trace.timestamp).toLocaleTimeString()}
                </span>
            ),
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={traces}
            rowKey="trace_id"
            size="small"
            onRow={(trace) => ({
                onClick: () => onSelectTrace(selectedTraceId === trace.trace_id ? null : trace.trace_id),
                className: selectedTraceId === trace.trace_id ? 'bg-fill-highlight' : 'cursor-pointer',
            })}
            emptyState="No traces found matching your filters"
        />
    )
}
