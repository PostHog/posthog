import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parse as parseYaml } from 'yaml'
import { z } from 'zod'

/**
 * Benchmark task file schema — the objective function for the MCP agent
 * experience. Tasks are sampled from real agent intents (paraphrased, never
 * verbatim) and describe what a competent agent should achieve against a
 * live MCP server, which tools it is expected to reach for, and optionally a
 * deterministic probe call the runner can execute without an LLM.
 */

export const TASK_CATEGORIES = [
    'sql',
    'data-schema',
    'product-analytics',
    'insights',
    'error-tracking',
    'feature-flags',
    'session-replay',
    'llm-analytics',
    'logs',
    'dashboards',
    'docs',
    'project',
    'mcp-analytics',
    'metrics',
] as const

export const BenchmarkProbeSchema = z.object({
    // Probes must reference read-only tools; the runner refuses to execute a
    // probe whose tool lacks readOnlyHint so a bad fixture can't mutate data.
    tool: z.string().min(1),
    args: z.record(z.string(), z.unknown()).default({}),
    max_ms: z.number().int().positive().default(15_000),
})

export const BenchmarkTaskSchema = z.object({
    id: z
        .string()
        .regex(/^[a-z0-9][a-z0-9-]+$/, 'task ids are kebab-case')
        .max(64),
    category: z.enum(TASK_CATEGORIES),
    // The user-visible goal the agent is given, written like a real request.
    intent: z.string().min(10),
    // Tools a competent agent is expected to call to complete the task.
    expected_tools: z.array(z.string().min(1)).min(1),
    // Tools that also count as a reasonable path (no tool-selection penalty).
    acceptable_tools: z.array(z.string().min(1)).default([]),
    // Plain-language pass condition consumed by the agent-mode judge.
    success_criteria: z.string().min(10),
    probe: BenchmarkProbeSchema.optional(),
})

export const BenchmarkFileSchema = z.object({
    version: z.literal(0),
    tasks: z.array(BenchmarkTaskSchema).min(1),
})

export type BenchmarkProbe = z.infer<typeof BenchmarkProbeSchema>
export type BenchmarkTask = z.infer<typeof BenchmarkTaskSchema>
export type BenchmarkFile = z.infer<typeof BenchmarkFileSchema>

export const DEFAULT_BENCHMARK_PATH = fileURLToPath(new URL('./tasks.yaml', import.meta.url))

export function loadBenchmark(path: string = DEFAULT_BENCHMARK_PATH): BenchmarkFile {
    return BenchmarkFileSchema.parse(parseYaml(readFileSync(path, 'utf-8')))
}

export function referencedTools(task: BenchmarkTask): string[] {
    return [...new Set([...task.expected_tools, ...task.acceptable_tools, ...(task.probe ? [task.probe.tool] : [])])]
}
