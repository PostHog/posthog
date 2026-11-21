import { describe, expect, it } from 'vitest'

import { collectToolExclusions } from '../../scripts/lib/tool-exclusions.mjs'

const tool = (extra: Record<string, unknown> = {}): Record<string, unknown> => ({
    enabled: true,
    operation: 'cohorts_partial_update',
    ...extra,
})

describe('collectToolExclusions', () => {
    it.each([
        ['an empty and a non-empty list', {}, { exclude_params: ['groups'] }],
        ['two different lists', { exclude_params: ['groups'] }, { exclude_params: ['groups', 'count'] }],
    ])('refuses tools on one operation with %s', (_name, first, second) => {
        // The operation has one schema, so a mismatch lets a tool without a list lose the other tool's excluded params.
        expect(() =>
            collectToolExclusions({ 'tool-a': tool(first), 'tool-b': tool(second) }, 'cohorts/tools.yaml')
        ).toThrow('tool-a and tool-b both use cohorts_partial_update with different exclude_params')
    })

    it('accepts the same list in any order, and ignores tools with their own input_schema', () => {
        const { operationIds, schemaExclusions } = collectToolExclusions(
            {
                'tool-a': tool({ exclude_params: ['groups', 'count'] }),
                'tool-b': tool({ exclude_params: ['count', 'groups'] }),
                'tool-c': tool({ input_schema: 'CustomSchema' }),
                'tool-d': tool({ enabled: false }),
            },
            'cohorts/tools.yaml'
        )

        expect([...operationIds]).toEqual(['cohorts_partial_update'])
        expect(schemaExclusions.get('cohorts_partial_update')).toEqual(['count', 'groups'])
    })
})
