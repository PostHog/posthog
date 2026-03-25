import { describe, expect, it } from 'vitest'

import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'

import { MAX_TOOL_NAME_LENGTH, TOOL_NAME_PATTERN } from '../../scripts/yaml-config-schema'

describe('Tool name validation', () => {
    const allTools = { ...TOOL_MAP, ...GENERATED_TOOL_MAP }

    it.each(Object.keys(allTools))('%s — name matches map key, length, and pattern', (mapKey) => {
        const factory = allTools[mapKey]!
        const tool = factory()

        expect(tool.name).toBe(mapKey)
        expect(tool.name).toMatch(TOOL_NAME_PATTERN)
        expect(tool.name.length).toBeLessThanOrEqual(MAX_TOOL_NAME_LENGTH)
    })
})
