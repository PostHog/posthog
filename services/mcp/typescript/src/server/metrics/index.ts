import { collectDefaultMetrics, Registry, Counter, Histogram } from 'prom-client'

export class Metrics {
    readonly registry: Registry
    private readonly requestCounter: Counter
    private readonly requestDuration: Histogram
    private readonly toolCallCounter: Counter

    constructor() {
        this.registry = new Registry()
        collectDefaultMetrics({ register: this.registry })

        this.requestCounter = new Counter({
            name: 'mcp_requests_total',
            help: 'Total number of MCP requests',
            labelNames: ['method', 'status'],
            registers: [this.registry],
        })

        this.requestDuration = new Histogram({
            name: 'mcp_request_duration_seconds',
            help: 'Duration of MCP requests in seconds',
            labelNames: ['method'],
            buckets: [0.1, 0.5, 1, 2, 5, 10, 30, 60],
            registers: [this.registry],
        })

        this.toolCallCounter = new Counter({
            name: 'mcp_tool_calls_total',
            help: 'Total number of MCP tool calls',
            labelNames: ['tool', 'status'],
            registers: [this.registry],
        })
    }

    incRequest(method: string, status: string): void {
        this.requestCounter.inc({ method, status })
    }

    observeDuration(method: string, seconds: number): void {
        this.requestDuration.observe({ method }, seconds)
    }

    incToolCall(tool: string, status: 'success' | 'error'): void {
        this.toolCallCounter.inc({ tool, status })
    }
}
