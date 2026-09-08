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
    'data-catalog',
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

/** Prefix every seeded entity carries, so a fixture is never mistaken for real project data. */
export const FIXTURE_KEY_PREFIX = 'mcp-eval-'

/** Tag the seeder puts on every fixture flag, so a project's own flags stay distinguishable. */
export const FIXTURE_TAG = 'mcp-eval'

/** Both fixture lists name keys the same seeder owns, so they validate through one schema. */
const FixtureFlagKeySchema = z
    .string()
    .regex(new RegExp(`^${FIXTURE_KEY_PREFIX}[a-z0-9-]+$`), `flag fixture keys start with ${FIXTURE_KEY_PREFIX}`)
    .max(200)

export const BenchmarkFlagFixtureSchema = z
    .object({
        key: FixtureFlagKeySchema,
        name: z.string().min(1),
        active: z.boolean(),
        archived: z.boolean(),
        // Release conditions, variants and payloads, in the API's own shape. Tasks that assert
        // an edit preserved unrelated configuration need something here to preserve.
        filters: z.record(z.string(), z.unknown()).default({}),
    })
    .strict()
    // The API disables a flag on the way to archiving it, so a fixture asking for both would
    // describe a state the seeder cannot leave the flag in.
    .refine((fixture) => !(fixture.archived && fixture.active), 'an archived fixture flag cannot also be active')

// Strict all the way down, because every fixture container defaults to empty. A misspelled
// key would otherwise be stripped, leaving the seeder nothing to write and no error to say so.
export const BenchmarkFixturesSchema = z
    .object({
        feature_flags: z.array(BenchmarkFlagFixtureSchema).default([]),
        // Keys a task is asked to create. The seeder soft-deletes each one, so the create
        // path is exercised rather than a second run hitting an already-taken key.
        absent_feature_flags: z.array(FixtureFlagKeySchema).default([]),
    })
    .strict()

export const BenchmarkFileSchema = z
    .object({
        version: z.literal(2),
        // Entities `runner/seed.ts` creates and resets before an agent-mode run, so tasks that
        // mutate state start from a known place and score the same on a second run.
        fixtures: BenchmarkFixturesSchema.default({ feature_flags: [], absent_feature_flags: [] }),
        tasks: z.array(BenchmarkTaskSchema).min(1),
    })
    .strict()

export type BenchmarkProbe = z.infer<typeof BenchmarkProbeSchema>
export type BenchmarkTask = z.infer<typeof BenchmarkTaskSchema>
export type BenchmarkFlagFixture = z.infer<typeof BenchmarkFlagFixtureSchema>
export type BenchmarkFixtures = z.infer<typeof BenchmarkFixturesSchema>
export type BenchmarkFile = z.infer<typeof BenchmarkFileSchema>

export const DEFAULT_BENCHMARK_PATH = fileURLToPath(new URL('./tasks.yaml', import.meta.url))

export function loadBenchmark(path: string = DEFAULT_BENCHMARK_PATH): BenchmarkFile {
    return BenchmarkFileSchema.parse(parseYaml(readFileSync(path, 'utf-8')))
}

/**
 * Fixture flag keys a task's intent names. Task independence rides on this: two tasks that
 * mutate the same fixture flag make the run order-dependent and stop a second run from
 * starting where the first one did, so the fixture test asserts no key is named twice.
 */
export function fixtureFlagKeysInIntent(task: BenchmarkTask, fixtures: BenchmarkFixtures): string[] {
    return fixtureFlagKeys(fixtures).filter((key) => task.intent.includes(key))
}

/** Every flag key the seeder owns — the ones it writes and the ones it clears. */
export function fixtureFlagKeys(fixtures: BenchmarkFixtures): string[] {
    return [...fixtures.feature_flags.map((fixture) => fixture.key), ...fixtures.absent_feature_flags]
}

export function referencedTools(task: BenchmarkTask): string[] {
    return [...new Set([...task.expected_tools, ...task.acceptable_tools, ...(task.probe ? [task.probe.tool] : [])])]
}

/**
 * Tools that MUST be advertised for a task to be runnable: the expected path
 * plus any deterministic probe tool. `acceptable_tools` are optional
 * alternatives — often feature-gated — so a missing one is not a benchmark
 * failure and is deliberately excluded here.
 */
export function requiredTools(task: BenchmarkTask): string[] {
    return [...new Set([...task.expected_tools, ...(task.probe ? [task.probe.tool] : [])])]
}
