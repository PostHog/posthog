import { describe, expect, it } from 'vitest'

import { getToolDefinitions } from '@/tools/toolDefinitions'

import { TASK_CATEGORIES, loadBenchmark, referencedTools } from '../../evals/benchmark/schema'

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

    it('probes exercise a tool the task expects', () => {
        const mismatched = loadBenchmark()
            .tasks.filter((task) => task.probe)
            .filter((task) => ![...task.expected_tools, ...task.acceptable_tools].includes(task.probe!.tool))
            .map((task) => task.id)
        expect(mismatched).toEqual([])
    })
})
