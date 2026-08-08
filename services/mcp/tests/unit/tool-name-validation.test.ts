import { describe, expect, it } from 'vitest'

import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { mergeToolFactories } from '@/tools/mergeToolFactories'

import { MAX_TOOL_NAME_LENGTH, TOOL_NAME_PATTERN } from '../../scripts/yaml-config-schema'

describe('Tool name validation', () => {
    // Hand-written factories win on collision (matches production merge order).
    const allTools = mergeToolFactories(GENERATED_TOOL_MAP, TOOL_MAP)

    it.each(Object.keys(allTools))('%s — name matches map key, length, and pattern', (mapKey) => {
        const factory = allTools[mapKey]!
        const tool = factory()

        expect(tool.name).toBe(mapKey)
        expect(tool.name).toMatch(TOOL_NAME_PATTERN)
        expect(tool.name.length).toBeLessThanOrEqual(MAX_TOOL_NAME_LENGTH)
    })
})
