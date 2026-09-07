import { describe, expect, it } from 'vitest'

import { getToolDefinitions } from '@/tools/toolDefinitions'

import {
    TASK_CATEGORIES,
    fixtureFlagKeys,
    fixtureFlagKeysInIntent,
    loadBenchmark,
    referencedTools,
} from '../../evals/benchmark/schema'

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

    it('probes exercise a tool the task expects', () => {
        const mismatched = loadBenchmark()
            .tasks.filter((task) => task.probe)
            .filter((task) => ![...task.expected_tools, ...task.acceptable_tools].includes(task.probe!.tool))
            .map((task) => task.id)
        expect(mismatched).toEqual([])
    })
})
