import { describe, expect, it } from 'vitest'

import type { GroupType } from '@/api/client'
import { buildGroupTypesBlock, buildInstructionsV2 } from '@/lib/instructions'

const MOCK_TEMPLATE = `### Basic functionality
Some instructions here.

{guidelines}

### Examples
Some examples here.

{group_types}`

describe('buildGroupTypesBlock', () => {
    it('should format group types with singular and plural names', () => {
        const groupTypes: GroupType[] = [
            { group_type: 'company', group_type_index: 0, name_singular: 'Company', name_plural: 'Companies' },
            { group_type: 'project', group_type_index: 1, name_singular: 'Project', name_plural: 'Projects' },
        ]
        const result = buildGroupTypesBlock(groupTypes)
        expect(result).toContain('### Group type mapping')
        expect(result).toContain('- Index 0: "company" (Company / Companies)')
        expect(result).toContain('- Index 1: "project" (Project / Projects)')
    })

    it('should omit singular name when null', () => {
        const groupTypes: GroupType[] = [
            { group_type: 'workspace', group_type_index: 0, name_singular: null, name_plural: null },
        ]
        const result = buildGroupTypesBlock(groupTypes)
        expect(result).toContain('- Index 0: "workspace"')
        expect(result).not.toContain('(null)')
        expect(result).not.toContain('()')
    })

    it('should return empty string for undefined', () => {
        expect(buildGroupTypesBlock(undefined)).toBe('')
    })

    it('should return empty string for empty array', () => {
        expect(buildGroupTypesBlock([])).toBe('')
    })
})

describe('buildInstructionsV2', () => {
    it('should replace guidelines and group_types placeholders', () => {
        const groupTypes: GroupType[] = [
            { group_type: 'company', group_type_index: 0, name_singular: 'Company', name_plural: 'Companies' },
        ]
        const result = buildInstructionsV2(MOCK_TEMPLATE, '  some guidelines  ', groupTypes)
        expect(result).toContain('some guidelines')
        expect(result).toContain('### Group type mapping')
        expect(result).toContain('- Index 0: "company" (Company / Companies)')
        expect(result).not.toContain('{guidelines}')
        expect(result).not.toContain('{group_types}')
    })

    it('should leave no placeholders when no group types', () => {
        const result = buildInstructionsV2(MOCK_TEMPLATE, 'guidelines', undefined)
        expect(result).not.toContain('{guidelines}')
        expect(result).not.toContain('{group_types}')
        expect(result).not.toContain('### Group type mapping')
    })

    it('should trim guidelines whitespace', () => {
        const result = buildInstructionsV2(MOCK_TEMPLATE, '  padded  ', undefined)
        expect(result).toContain('padded')
        expect(result).not.toContain('  padded  ')
    })
})
