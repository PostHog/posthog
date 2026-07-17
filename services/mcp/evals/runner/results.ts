/**
 * Pure result types + aggregation for eval runs. Kept free of I/O so the
 * scoring math is unit-testable — campaign keep/discard decisions ride on
 * these numbers.
 */

export type ProbeStatus =
    | 'ok'
    | 'tool_error' // server answered with isError: true
    | 'transport_error' // request failed or threw
    | 'timeout'
    | 'refused_not_read_only' // advertised annotations don't mark the tool read-only
    | 'skipped_not_advertised'

export interface ToolMiss {
    task_id: string
    tool: string
}

export interface ProbeResult {
    task_id: string
    tool: string
    status: ProbeStatus
    latency_ms?: number
    error_snippet?: string
}

export interface ProbeRunSummary {
    benchmark_version: number
    tasks_total: number
    tools_referenced: number
    /** Referenced tools the server did not advertise — discoverability misses. */
    tool_misses: ToolMiss[]
    probes_total: number
    probes_ok: number
    probes_failed: number
    latency_p50_ms: number | null
    latency_p95_ms: number | null
    probes: ProbeResult[]
}

export function percentile(sortedValues: number[], p: number): number | null {
    if (sortedValues.length === 0) {
        return null
    }
    const rank = Math.min(sortedValues.length - 1, Math.max(0, Math.ceil((p / 100) * sortedValues.length) - 1))
    return sortedValues[rank] ?? null
}

export function summarize(input: {
    benchmarkVersion: number
    tasksTotal: number
    toolsReferenced: number
    toolMisses: ToolMiss[]
    probes: ProbeResult[]
}): ProbeRunSummary {
    const latencies = input.probes
        .map((probe) => probe.latency_ms)
        .filter((value): value is number => typeof value === 'number')
        .sort((a, b) => a - b)
    const ok = input.probes.filter((probe) => probe.status === 'ok').length

    return {
        benchmark_version: input.benchmarkVersion,
        tasks_total: input.tasksTotal,
        tools_referenced: input.toolsReferenced,
        tool_misses: input.toolMisses,
        probes_total: input.probes.length,
        probes_ok: ok,
        probes_failed: input.probes.length - ok,
        latency_p50_ms: percentile(latencies, 50),
        latency_p95_ms: percentile(latencies, 95),
        probes: input.probes,
    }
}

export function formatSummary(summary: ProbeRunSummary): string {
    const lines = [
        `benchmark v${summary.benchmark_version}: ${summary.tasks_total} tasks, ${summary.tools_referenced} referenced tools`,
        `tool presence: ${summary.tool_misses.length === 0 ? 'all advertised' : `${summary.tool_misses.length} MISSING`}`,
        ...summary.tool_misses.map((miss) => `  MISSING ${miss.tool} (task ${miss.task_id})`),
        `probes: ${summary.probes_ok}/${summary.probes_total} ok` +
            (summary.latency_p50_ms !== null
                ? ` (p50 ${summary.latency_p50_ms}ms, p95 ${summary.latency_p95_ms}ms)`
                : ''),
        ...summary.probes
            .filter((probe) => probe.status !== 'ok')
            .map(
                (probe) =>
                    `  ${probe.status.toUpperCase()} ${probe.tool} (task ${probe.task_id})${probe.error_snippet ? `: ${probe.error_snippet}` : ''}`
            ),
    ]
    return lines.join('\n')
}
