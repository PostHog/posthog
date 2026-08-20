import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/cdp_function_templates'

// Agents that list templates then retrieve one naturally pass the `id` field the
// list endpoint returns, but production traces show some still send the older
// `template_id` / `templateId` spellings. Those aliases must normalize to the
// canonical `id` (canonical key wins on conflict) or the retrieve tool rejects
// the call before it reaches the API.
describe('cdp-function-templates-retrieve id aliases', () => {
    const ALIAS_KEYS = ['template_id', 'templateId'] as const
    const schema = GENERATED_TOOLS['cdp-function-templates-retrieve']!().schema

    it.each([
        ['id', { id: 'template-slack' }, 'template-slack'],
        ['template_id', { template_id: 'template-slack' }, 'template-slack'],
        ['templateId', { templateId: 'template-slack' }, 'template-slack'],
        ['id over aliases on conflict', { id: 'template-slack', template_id: 'template-geoip' }, 'template-slack'],
        [
            'first-listed alias on alias conflict',
            { template_id: 'template-slack', templateId: 'template-geoip' },
            'template-slack',
        ],
    ])('accepts %s', (_label, input, expected) => {
        const result = schema.safeParse(input)
        expect(result.success).toBe(true)
        const data = result.data as Record<string, unknown>
        expect(data.id).toEqual(expected)
        for (const alias of ALIAS_KEYS) {
            expect(data).not.toHaveProperty(alias)
        }
    })

    it('still rejects a call with no identifier', () => {
        expect(schema.safeParse({}).success).toBe(false)
    })
})
