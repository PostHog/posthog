/**
 * Tool-selection scoring — the objective function for "did the agent reach for
 * the right tool?". Kept free of I/O so the math is unit-testable: campaign
 * keep/discard decisions ride on these numbers.
 *
 * Two rates, because "correct" and "unbiased" are different questions. A task
 * that expects `query-trends` and accepts `execute-sql` is *answered* either
 * way, so `tool_selection_accuracy` counts both — that is the contract the
 * fixtures document. `expected_path_rate` counts only the expected tool, so it
 * falls when the agent keeps substituting the escape hatch for the typed path.
 */

import type { BenchmarkTask } from '../benchmark/schema'

/**
 * The catalog's general-purpose escape hatch. Every structured query tool has a
 * narrower contract than raw SQL, so this is what an agent falls back to when it
 * skips the typed path — which is why its call share is the reliance signal.
 */
export const RAW_SQL_TOOL = 'execute-sql'

export type SelectionVerdict =
    | 'expected' // reached an expected tool — the intended path
    | 'substituted' // reached only acceptable tools — answered, but off the intended path
    | 'off_benchmark' // reached neither
    | 'no_calls' // never successfully called anything

/** Worst first, so the summary leads with what needs attention. */
const VERDICT_RANK: Record<SelectionVerdict, number> = {
    no_calls: 0,
    off_benchmark: 1,
    substituted: 2,
    expected: 3,
}

export interface TaskSelection {
    task_id: string
    category: string
    verdict: SelectionVerdict
    /** Successful calls in the order made, so a reviewer can read the path taken. */
    calls: string[]
    expected: string[]
    /** Acceptable tools reached in place of the expected path (empty unless substituted). */
    substituted: string[]
}

export interface SubstituteCount {
    tool: string
    tasks: number
}

/**
 * How heavily the agent leaned on raw SQL across tasks where SQL was NOT the
 * expected path. This is the part a last-call or any-call check misses: an agent
 * can run six SQL queries, then close with `query-trends`, and still look clean.
 */
export interface SqlReliance {
    /** Tasks whose expected path is something other than raw SQL. */
    tasks: number
    calls_total: number
    sql_calls: number
    /** `sql_calls / calls_total`, or null when no calls were made on those tasks. */
    share: number | null
    /** How many of those tasks touched raw SQL at all. */
    tasks_touching_sql: number
}

export interface SelectionSummary {
    tasks_scored: number
    /** Share reaching an expected OR acceptable tool. Null when nothing was scored. */
    tool_selection_accuracy: number | null
    /** Share reaching an *expected* tool. The bias-sensitive number. */
    expected_path_rate: number | null
    substitutes: SubstituteCount[]
    sql_reliance: SqlReliance
    tasks: TaskSelection[]
}

/**
 * Score one task against the calls the agent actually made.
 *
 * `calls` must already be filtered to successful calls, in order. A task with
 * several expected tools passes on reaching ANY of them — the fixtures list the
 * tools a competent agent would use, not a set it must exhaust.
 */
export function scoreTask(task: BenchmarkTask, calls: string[]): TaskSelection {
    const expected = new Set(task.expected_tools)
    const acceptable = new Set(task.acceptable_tools)
    const base = {
        task_id: task.id,
        category: task.category,
        calls,
        expected: task.expected_tools,
    }

    if (calls.length === 0) {
        return { ...base, verdict: 'no_calls', substituted: [] }
    }
    if (calls.some((call) => expected.has(call))) {
        return { ...base, verdict: 'expected', substituted: [] }
    }

    // Deduplicated but call-ordered: which acceptable tools stood in for the
    // expected path is the substitution signal we aggregate below.
    const substituted = [...new Set(calls.filter((call) => acceptable.has(call)))]
    return {
        ...base,
        verdict: substituted.length > 0 ? 'substituted' : 'off_benchmark',
        substituted,
    }
}

function countSubstitutes(tasks: TaskSelection[]): SubstituteCount[] {
    const counts = new Map<string, number>()
    for (const task of tasks.filter((candidate) => candidate.verdict === 'substituted')) {
        for (const tool of task.substituted) {
            counts.set(tool, (counts.get(tool) ?? 0) + 1)
        }
    }
    return [...counts.entries()]
        .map(([tool, count]) => ({ tool, tasks: count }))
        .sort((a, b) => b.tasks - a.tasks || a.tool.localeCompare(b.tool))
}

function measureSqlReliance(scored: TaskSelection[]): SqlReliance {
    const offPath = scored.filter((task) => !task.expected.includes(RAW_SQL_TOOL))
    const callsTotal = offPath.reduce((sum, task) => sum + task.calls.length, 0)
    const sqlCalls = offPath.reduce((sum, task) => sum + task.calls.filter((call) => call === RAW_SQL_TOOL).length, 0)

    return {
        tasks: offPath.length,
        calls_total: callsTotal,
        sql_calls: sqlCalls,
        share: callsTotal === 0 ? null : sqlCalls / callsTotal,
        tasks_touching_sql: offPath.filter((task) => task.calls.includes(RAW_SQL_TOOL)).length,
    }
}

export function summarizeSelection(scored: TaskSelection[]): SelectionSummary {
    const total = scored.length
    const onBenchmark = scored.filter((task) => task.verdict === 'expected' || task.verdict === 'substituted').length
    const onExpected = scored.filter((task) => task.verdict === 'expected').length

    return {
        tasks_scored: total,
        tool_selection_accuracy: total === 0 ? null : onBenchmark / total,
        expected_path_rate: total === 0 ? null : onExpected / total,
        substitutes: countSubstitutes(scored),
        sql_reliance: measureSqlReliance(scored),
        tasks: [...scored].sort(
            (a, b) => VERDICT_RANK[a.verdict] - VERDICT_RANK[b.verdict] || a.task_id.localeCompare(b.task_id)
        ),
    }
}

function percent(value: number | null): string {
    return value === null ? 'n/a' : `${Math.round(value * 1000) / 10}%`
}

export function formatSelectionSummary(summary: SelectionSummary): string {
    const { sql_reliance: sql } = summary
    const lines = [
        `tool selection: ${summary.tasks_scored} tasks scored`,
        `  accuracy (expected or acceptable): ${percent(summary.tool_selection_accuracy)}`,
        `  expected path taken:               ${percent(summary.expected_path_rate)}`,
        `  raw SQL share where SQL was not expected: ${percent(sql.share)}` +
            ` (${sql.sql_calls}/${sql.calls_total} calls, ${sql.tasks_touching_sql}/${sql.tasks} tasks)`,
    ]

    if (summary.substitutes.length > 0) {
        lines.push('  substituted for an expected tool:')
        lines.push(...summary.substitutes.map((entry) => `    ${entry.tool} on ${entry.tasks} task(s)`))
    }

    const offPath = summary.tasks.filter((task) => task.verdict !== 'expected')
    if (offPath.length > 0) {
        lines.push('  tasks off the expected path:')
        lines.push(
            ...offPath.map(
                (task) =>
                    `    ${task.verdict.toUpperCase()} ${task.task_id}` +
                    ` (expected ${task.expected.join('|')}; called ${task.calls.join(' → ') || 'nothing'})`
            )
        )
    }

    return lines.join('\n')
}
