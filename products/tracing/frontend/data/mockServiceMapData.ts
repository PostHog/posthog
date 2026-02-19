import type { TraceSummary } from './mockTraceData'
import { MOCK_TRACES } from './mockTraceData'

export interface ServiceNodeData {
    id: string
    trace_count: number
    span_count: number
    error_count: number
    avg_duration_ms: number
}

export interface ServiceEdgeData {
    [key: string]: unknown
    source: string
    target: string
    request_count: number
    error_count: number
}

export interface ServiceGraph {
    nodes: ServiceNodeData[]
    edges: ServiceEdgeData[]
}

export function deriveServiceGraph(traces: TraceSummary[]): ServiceGraph {
    const nodeMap = new Map<string, ServiceNodeData>()
    const edgeMap = new Map<string, ServiceEdgeData>()
    const serviceTraces = new Map<string, Set<string>>()

    for (const trace of traces) {
        const spanById = new Map(trace.spans.map((s) => [s.span_id, s]))

        for (const span of trace.spans) {
            // Aggregate node data
            if (!nodeMap.has(span.service_name)) {
                nodeMap.set(span.service_name, {
                    id: span.service_name,
                    trace_count: 0,
                    span_count: 0,
                    error_count: 0,
                    avg_duration_ms: 0,
                })
            }
            const node = nodeMap.get(span.service_name)!
            node.span_count++
            if (span.status_code === 'error') {
                node.error_count++
            }
            // Running average
            node.avg_duration_ms += (span.duration_ms - node.avg_duration_ms) / node.span_count

            // Track unique traces per service
            if (!serviceTraces.has(span.service_name)) {
                serviceTraces.set(span.service_name, new Set())
            }
            serviceTraces.get(span.service_name)!.add(trace.trace_id)

            // Build edges from parent→child across different services
            if (span.parent_span_id) {
                const parent = spanById.get(span.parent_span_id)
                if (parent && parent.service_name !== span.service_name) {
                    const edgeKey = `${parent.service_name}→${span.service_name}`
                    if (!edgeMap.has(edgeKey)) {
                        edgeMap.set(edgeKey, {
                            source: parent.service_name,
                            target: span.service_name,
                            request_count: 0,
                            error_count: 0,
                        })
                    }
                    const edge = edgeMap.get(edgeKey)!
                    edge.request_count++
                    if (span.status_code === 'error') {
                        edge.error_count++
                    }
                }
            }
        }
    }

    // Set trace counts from the set sizes
    for (const [serviceName, traceIds] of serviceTraces) {
        const node = nodeMap.get(serviceName)
        if (node) {
            node.trace_count = traceIds.size
        }
    }

    return {
        nodes: Array.from(nodeMap.values()),
        edges: Array.from(edgeMap.values()),
    }
}

export const MOCK_SERVICE_GRAPH = deriveServiceGraph(MOCK_TRACES)
