import { describe, expect, it } from 'vitest'

import { getToolDefinitions } from '@/tools/toolDefinitions'

import {
    BenchmarkFileSchema,
    TASK_CATEGORIES,
    fixtureFlagKeys,
    fixtureFlagKeysInIntent,
    loadBenchmark,
    referencedTools,
} from '../../evals/benchmark/schema'

const FLAG_FIXTURE = {
    key: 'mcp-eval-enable-me',
    name: 'Enable target',
    active: false,
    archived: false,
}

const FIXTURES_BLOCK = { feature_flags: [FLAG_FIXTURE], absent_feature_flags: ['mcp-eval-create-me'] }

const TASK = {
    id: 'enable-a-flag',
    category: 'feature-flags',
    intent: 'Turn the mcp-eval-enable-me flag on.',
    expected_tools: ['feature-flag-enable'],
    success_criteria: 'The flag is enabled and the reply says so.',
}

describe('MCP eval benchmark fixtures', () => {
    // Loaded inside each test (not at describe scope) so a broken fixture or
    // catalog fails the owning test with a real error instead of blowing up
    // vitest's collection phase.
    it('parses against the schema with unique task ids', () => {
        const benchmark = loadBenchmark()
        const ids = benchmark.tasks.map((task) => task.id)
        expect(new Set(ids).size).toBe(ids.length)
    })

    it('only references tools that exist in the catalog', () => {
        const known = new Set(Object.keys(getToolDefinitions()))
        const unknown = loadBenchmark().tasks.flatMap((task) =>
            referencedTools(task)
                .filter((tool) => !known.has(tool))
                .map((tool) => `${task.id} → ${tool}`)
        )
        expect(unknown).toEqual([])
    })

    it('uses every declared task category', () => {
        const used = new Set(loadBenchmark().tasks.map((task) => task.category))
        const unused = TASK_CATEGORIES.filter((category) => !used.has(category))
        expect(unused).toEqual([])
    })

    it('only probes read-only tools', () => {
        const catalog = getToolDefinitions()
        const unsafe = loadBenchmark()
            .tasks.filter((task) => task.probe)
            .filter((task) => catalog[task.probe!.tool]?.annotations?.readOnlyHint !== true)
            .map((task) => `${task.id} → ${task.probe!.tool}`)
        expect(unsafe).toEqual([])
    })

    // Both halves of the seeded-fixture contract in one assertion. Zero tasks means the
    // seeder writes state nothing reads, which is how a renamed key silently stops being
    // exercised. Two or more means those tasks share a flag, which is the order-dependence
    // v2 removed: whichever ran first decides what the next one starts from.
    it('names every seeded flag fixture in exactly one task intent', () => {
        const benchmark = loadBenchmark()
        const tasksByKey = new Map(fixtureFlagKeys(benchmark.fixtures).map((key) => [key, [] as string[]]))
        for (const task of benchmark.tasks) {
            for (const key of fixtureFlagKeysInIntent(task, benchmark.fixtures)) {
                tasksByKey.get(key)!.push(task.id)
            }
        }
        const wrong = [...tasksByKey.entries()]
            .filter(([, taskIds]) => taskIds.length !== 1)
            .map(([key, taskIds]) => `${key} → ${taskIds.length ? taskIds.join(', ') : 'no task'}`)
        expect(wrong).toEqual([])
    })

    // Every fixture container defaults to empty, so a stripped key used to read as "no
    // fixtures" rather than as a typo: the seeder wrote nothing, exited 0, and the test
    // above passed over an empty map while the next run scored the lifecycle tasks
    // against flags that did not exist.
    it.each([
        { name: 'the fixtures block spelled correctly', fixtures: FIXTURES_BLOCK, parses: true },
        { name: 'a misspelled fixture list', fixtures: { feature_flag: [FLAG_FIXTURE] }, parses: false },
        {
            name: 'a misspelled field on a fixture flag',
            fixtures: { feature_flags: [{ ...FLAG_FIXTURE, activee: true }] },
            parses: false,
        },
        // `clearFlag` soft-deletes whatever key it is handed, so a fixture key without
        // the prefix would delete one of the project's real flags rather than a fixture.
        {
            name: 'a fixture key missing the mcp-eval- prefix',
            fixtures: { feature_flags: [{ ...FLAG_FIXTURE, key: 'billing-killswitch' }] },
            parses: false,
        },
        {
            name: 'an absent-flag key missing the mcp-eval- prefix',
            fixtures: { ...FIXTURES_BLOCK, absent_feature_flags: ['billing-killswitch'] },
            parses: false,
        },
        // The API disables a flag on the way to archiving it, so the seeder cannot leave
        // a flag in both states and a fixture asking for both describes nothing.
        {
            name: 'a fixture that is both archived and active',
            fixtures: { feature_flags: [{ ...FLAG_FIXTURE, active: true, archived: true }] },
            parses: false,
        },
    ])('the schema accepts $name: $parses', ({ fixtures, parses }) => {
        expect(BenchmarkFileSchema.safeParse({ version: 2, fixtures, tasks: [TASK] }).success).toBe(parses)
    })

    it('rejects a misspelled fixtures block', () => {
        const parsed = BenchmarkFileSchema.safeParse({ version: 2, fixtuers: FIXTURES_BLOCK, tasks: [TASK] })

        expect(parsed.success).toBe(false)
    })

    it('probes exercise a tool the task expects', () => {
        const mismatched = loadBenchmark()
            .tasks.filter((task) => task.probe)
            .filter((task) => ![...task.expected_tools, ...task.acceptable_tools].includes(task.probe!.tool))
            .map((task) => task.id)
        expect(mismatched).toEqual([])
    })
})
