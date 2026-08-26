import { describe, expect, it } from 'vitest'

import type { BenchmarkTask } from '../../evals/benchmark/schema'
import { scoreTask, summarizeSelection } from '../../evals/runner/selection'

function task(id: string, expected: string[], acceptable: string[] = []): BenchmarkTask {
    return {
        id,
        category: 'product-analytics',
        intent: 'a realistic agent intent',
        expected_tools: expected,
        acceptable_tools: acceptable,
        success_criteria: 'returns the thing the intent asked for',
    }
}

describe('tool selection scoring', () => {
    it.each([
        {
            name: 'expected tool reached directly',
            calls: ['query-trends'],
            verdict: 'expected',
        },
        {
            name: 'expected tool reached after exploring via SQL',
            calls: ['execute-sql', 'execute-sql', 'query-trends'],
            verdict: 'expected',
        },
        {
            name: 'expected tool reached first, then SQL',
            calls: ['query-trends', 'execute-sql'],
            verdict: 'expected',
        },
        {
            name: 'only the acceptable substitute reached',
            calls: ['execute-sql'],
            verdict: 'substituted',
        },
        {
            name: 'neither expected nor acceptable reached',
            calls: ['feature-flag-get-all'],
            verdict: 'off_benchmark',
        },
        { name: 'no calls at all', calls: [], verdict: 'no_calls' },
    ])('scores $name as $verdict', ({ calls, verdict }) => {
        const scored = scoreTask(task('t', ['query-trends'], ['execute-sql', 'read-data-schema']), calls)
        expect(scored.verdict).toBe(verdict)
    })

    it('reports which acceptable tools stood in for the expected path', () => {
        const scored = scoreTask(task('t', ['query-funnel'], ['execute-sql', 'read-data-schema']), [
            'read-data-schema',
            'execute-sql',
            'execute-sql',
        ])

        expect(scored.verdict).toBe('substituted')
        // Deduplicated, so one substitute called twice counts as one substitution.
        expect(scored.substituted).toEqual(['read-data-schema', 'execute-sql'])
    })

    it('measures SQL reliance only over tasks where SQL was not the expected path', () => {
        const summary = summarizeSelection([
            // SQL is the expected path here, so these calls are on-path and must
            // not inflate the reliance share.
            scoreTask(task('sql-task', ['execute-sql']), ['execute-sql', 'execute-sql']),
            scoreTask(task('trends', ['query-trends'], ['execute-sql']), ['execute-sql', 'query-trends']),
            scoreTask(task('funnel', ['query-funnel'], ['execute-sql']), ['execute-sql']),
        ])

        expect(summary.sql_reliance).toEqual({
            tasks: 2,
            calls_total: 3,
            sql_calls: 2,
            share: 2 / 3,
            tasks_touching_sql: 2,
        })
    })

    it('separates answering the task from taking the expected path', () => {
        const summary = summarizeSelection([
            scoreTask(task('a', ['query-trends'], ['execute-sql']), ['query-trends']),
            scoreTask(task('b', ['query-funnel'], ['execute-sql']), ['execute-sql']),
            scoreTask(task('c', ['query-retention'], ['execute-sql']), ['execute-sql']),
            scoreTask(task('d', ['query-paths']), ['feature-flag-get-all']),
        ])

        // Three of four landed on a tool the fixtures accept...
        expect(summary.tool_selection_accuracy).toBe(0.75)
        // ...but only one took the expected path. That gap is the bias signal.
        expect(summary.expected_path_rate).toBe(0.25)
        expect(summary.substitutes).toEqual([{ tool: 'execute-sql', tasks: 2 }])
    })

    it.each([
        { name: 'nothing scored', scored: [] as ReturnType<typeof scoreTask>[], accuracy: null, share: null },
        {
            name: 'scored but no calls made',
            scored: [scoreTask(task('a', ['query-trends']), [])],
            accuracy: 0,
            share: null,
        },
    ])('keeps NaN out of the score artifact when $name', ({ scored, accuracy, share }) => {
        const summary = summarizeSelection(scored)

        expect(summary.tool_selection_accuracy).toBe(accuracy)
        expect(summary.sql_reliance.share).toBe(share)
        expect(JSON.stringify(summary)).not.toContain('NaN')
    })

    it('orders tasks worst verdict first so the summary leads with problems', () => {
        const summary = summarizeSelection([
            scoreTask(task('good', ['query-trends']), ['query-trends']),
            scoreTask(task('substituted', ['query-trends'], ['execute-sql']), ['execute-sql']),
            scoreTask(task('silent', ['query-trends']), []),
            scoreTask(task('wrong', ['query-trends']), ['feature-flag-get-all']),
        ])

        expect(summary.tasks.map((entry) => entry.task_id)).toEqual(['silent', 'wrong', 'substituted', 'good'])
    })
})
