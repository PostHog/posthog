import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/cdp_function_templates'

const schema = GENERATED_TOOLS['cdp-function-templates-retrieve']!().schema

describe('cdp-function-templates-retrieve schema', () => {
    it.each([
        ['template_id', { template_id: 'template-slack' }, 'template-slack'],
        // Every other PostHog tool names its identifier `id`, and cdp-function-templates-list
        // returns the template under `id`, so agents reach for `id` here too.
        ['id alias', { id: 'template-slack' }, 'template-slack'],
        [
            'template_id takes precedence over id',
            { template_id: 'template-geoip', id: 'template-slack' },
            'template-geoip',
        ],
    ])('accepts %s and normalizes to template_id', (_label, input, expected) => {
        const result = schema.safeParse(input)

        expect(result.success).toBe(true)
        expect(result.data).toEqual({ template_id: expected })
    })

    it('rejects input with no recognized identifier', () => {
        expect(schema.safeParse({}).success).toBe(false)
    })
})
