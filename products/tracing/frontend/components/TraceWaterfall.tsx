import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyMilliseconds } from 'lib/utils'

import type { Span, TraceSummary } from '../data/mockTraceData'
import { tracingSceneLogic } from '../tracingSceneLogic'
import { statusTagType } from './tracingUtils'

interface FlattenedSpan {
    span: Span
    depth: number
}

function flattenSpans(spans: Span[]): FlattenedSpan[] {
    const byParent = new Map<string, Span[]>()
    for (const span of spans) {
        const key = span.parent_span_id
        if (!byParent.has(key)) {
            byParent.set(key, [])
        }
        byParent.get(key)!.push(span)
    }

    const result: FlattenedSpan[] = []
    function walk(parentId: string, depth: number): void {
        const children = byParent.get(parentId) ?? []
        children.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
        for (const child of children) {
            result.push({ span: child, depth })
            walk(child.span_id, depth + 1)
        }
    }
    walk('', 0)
    return result
}

function serviceColor(serviceName: string, allServices: string[]): string {
    const index = allServices.indexOf(serviceName)
    return getSeriesColor(index >= 0 ? index : 0)
}

interface TraceWaterfallProps {
    trace: TraceSummary
}

export function TraceWaterfall({ trace }: TraceWaterfallProps): JSX.Element {
    const { selectedSpanId, selectedSpan } = useValues(tracingSceneLogic)
    const { setSelectedSpanId } = useActions(tracingSceneLogic)

    const flatSpans = flattenSpans(trace.spans)
    const allServices = [...new Set(trace.spans.map((s) => s.service_name))]
    const traceDuration = trace.duration_ms
    const traceStartMs = new Date(trace.timestamp).getTime()

    return (
        <div className="border rounded bg-bg-light p-4">
            <div className="flex items-center gap-3 mb-4">
                <span className="font-mono text-xs text-muted">
                    {trace.trace_id.slice(0, 8)}...{trace.trace_id.slice(-4)}
                </span>
                <LemonTag type={statusTagType(trace.status_code)}>{trace.status_code.toUpperCase()}</LemonTag>
                <span className="text-muted text-sm">{trace.span_count} spans</span>
                <span className="font-mono text-sm font-semibold">{humanFriendlyMilliseconds(trace.duration_ms)}</span>
            </div>

            {/* Time axis */}
            <div className="flex items-center text-xs text-muted mb-1 ml-[280px]">
                <span>0ms</span>
                <span className="flex-1 text-center">{humanFriendlyMilliseconds(traceDuration / 2)}</span>
                <span>{humanFriendlyMilliseconds(traceDuration)}</span>
            </div>

            {/* Span rows */}
            <div className="flex flex-col">
                {flatSpans.map(({ span, depth }) => {
                    const offsetMs = new Date(span.timestamp).getTime() - traceStartMs
                    const leftPct = traceDuration > 0 ? (offsetMs / traceDuration) * 100 : 0
                    const widthPct = traceDuration > 0 ? Math.max((span.duration_ms / traceDuration) * 100, 0.5) : 0
                    const color = serviceColor(span.service_name, allServices)
                    const isSelected = selectedSpanId === span.span_id

                    return (
                        <div
                            key={span.span_id}
                            className={`flex items-center py-1 cursor-pointer hover:bg-fill-highlight-100 rounded ${
                                isSelected ? 'bg-fill-highlight' : ''
                            }`}
                            onClick={() => setSelectedSpanId(isSelected ? null : span.span_id)}
                        >
                            {/* Label */}
                            <div
                                className="flex-shrink-0 w-[280px] truncate text-xs"
                                /* eslint-disable-next-line react/forbid-dom-props */
                                style={{ paddingLeft: depth * 20 + 8 }}
                            >
                                <span className="text-muted">{span.service_name}</span>
                                <span className="mx-1 text-muted">{'>'}</span>
                                <span className="font-medium">{span.name}</span>
                            </div>

                            {/* Bar */}
                            <div className="flex-1 relative h-6 mx-2">
                                <Tooltip title={`${span.name} — ${humanFriendlyMilliseconds(span.duration_ms)}`}>
                                    <div
                                        className="absolute top-0.5 bottom-0.5 rounded-sm"
                                        /* eslint-disable-next-line react/forbid-dom-props */
                                        style={{
                                            left: `${leftPct}%`,
                                            width: `${widthPct}%`,
                                            backgroundColor: color,
                                            minWidth: 2,
                                        }}
                                    />
                                </Tooltip>
                            </div>

                            {/* Duration */}
                            <div className="flex-shrink-0 w-16 text-right text-xs font-mono text-muted">
                                {humanFriendlyMilliseconds(span.duration_ms)}
                            </div>
                        </div>
                    )
                })}
            </div>

            {/* Selected span details */}
            {selectedSpan && (
                <div className="mt-4 border-t pt-4">
                    <div className="flex items-center gap-2 mb-3">
                        <span className="font-semibold text-sm">{selectedSpan.name}</span>
                        <LemonTag type={statusTagType(selectedSpan.status_code)}>
                            {selectedSpan.status_code.toUpperCase()}
                        </LemonTag>
                        <LemonTag type="muted">{selectedSpan.span_kind.toUpperCase()}</LemonTag>
                    </div>
                    {selectedSpan.status_message && (
                        <div className="text-danger text-sm mb-3">{selectedSpan.status_message}</div>
                    )}
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b">
                                <th className="text-left py-1 pr-4 text-muted font-medium w-1/3">Attribute</th>
                                <th className="text-left py-1 text-muted font-medium">Value</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr className="border-b border-border-light">
                                <td className="py-1 pr-4 font-mono text-xs">service.name</td>
                                <td className="py-1 font-mono text-xs">{selectedSpan.service_name}</td>
                            </tr>
                            <tr className="border-b border-border-light">
                                <td className="py-1 pr-4 font-mono text-xs">span.kind</td>
                                <td className="py-1 font-mono text-xs">{selectedSpan.span_kind}</td>
                            </tr>
                            <tr className="border-b border-border-light">
                                <td className="py-1 pr-4 font-mono text-xs">duration</td>
                                <td className="py-1 font-mono text-xs">
                                    {humanFriendlyMilliseconds(selectedSpan.duration_ms)}
                                </td>
                            </tr>
                            {Object.entries(selectedSpan.attributes).map(([key, value]) => (
                                <tr key={key} className="border-b border-border-light">
                                    <td className="py-1 pr-4 font-mono text-xs">{key}</td>
                                    <td className="py-1 font-mono text-xs">{value}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {selectedSpan.events.length > 0 && (
                        <div className="mt-3">
                            <h4 className="text-sm font-medium mb-2">Events</h4>
                            {selectedSpan.events.map((event, i) => (
                                <div key={i} className="mb-2 p-2 bg-bg-3000 rounded text-xs">
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className="font-semibold">{event.name}</span>
                                        <span className="text-muted">
                                            {new Date(event.timestamp).toLocaleTimeString()}
                                        </span>
                                    </div>
                                    {Object.entries(event.attributes).map(([key, value]) => (
                                        <div key={key} className="font-mono ml-2">
                                            <span className="text-muted">{key}:</span>{' '}
                                            <span className="whitespace-pre-wrap break-all">{value}</span>
                                        </div>
                                    ))}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
