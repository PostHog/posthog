import { describe, expect, it } from 'vitest'

import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { mergeToolFactories } from '@/tools/mergeToolFactories'

import { MAX_TOOL_NAME_LENGTH, TOOL_NAME_PATTERN } from '../../scripts/yaml-config-schema'

describe('Tool name validation', () => {
    const allTools = mergeToolFactories({ generated: GENERATED_TOOL_MAP, handwritten: TOOL_MAP })

    // A hand-written tool that shares a generated tool's name shadows it everywhere, so a
    // newly generated tool colliding with one would silently replace it.
    it('shadows only the generated tools it means to', () => {
        const shadowed = Object.keys(TOOL_MAP).filter((name) => name in GENERATED_TOOL_MAP)

        expect(shadowed.sort()).toEqual(['update-feature-flag'])
    })

    it.each(Object.keys(allTools))('%s — name matches map key, length, and pattern', (mapKey) => {
        const factory = allTools[mapKey]!
        const tool = factory()

        expect(tool.name).toBe(mapKey)
        expect(tool.name).toMatch(TOOL_NAME_PATTERN)
        expect(tool.name.length).toBeLessThanOrEqual(MAX_TOOL_NAME_LENGTH)
    })
})
