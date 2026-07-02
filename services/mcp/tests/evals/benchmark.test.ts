import { describe, expect, it } from 'vitest'

import { getToolDefinitions } from '@/tools/toolDefinitions'

import { loadBenchmark, referencedTools } from '../../evals/benchmark/schema'

describe('MCP eval benchmark fixtures', () => {
    const benchmark = loadBenchmark()
    const catalog = getToolDefinitions()

    it('parses against the schema with unique task ids', () => {
        const ids = benchmark.tasks.map((task) => task.id)
        expect(new Set(ids).size).toBe(ids.length)
    })

    it('only references tools that exist in the catalog', () => {
        const known = new Set(Object.keys(catalog))
        const unknown = benchmark.tasks.flatMap((task) =>
            referencedTools(task)
                .filter((tool) => !known.has(tool))
                .map((tool) => `${task.id} → ${tool}`)
        )
        expect(unknown).toEqual([])
    })

    it('only probes read-only tools', () => {
        const unsafe = benchmark.tasks
            .filter((task) => task.probe)
            .filter((task) => catalog[task.probe!.tool]?.annotations?.readOnlyHint !== true)
            .map((task) => `${task.id} → ${task.probe!.tool}`)
        expect(unsafe).toEqual([])
    })

    it('probes exercise a tool the task expects', () => {
        const mismatched = benchmark.tasks
            .filter((task) => task.probe)
            .filter((task) => ![...task.expected_tools, ...task.acceptable_tools].includes(task.probe!.tool))
            .map((task) => task.id)
        expect(mismatched).toEqual([])
    })
})
