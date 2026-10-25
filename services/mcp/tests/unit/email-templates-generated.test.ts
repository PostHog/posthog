import { describe, expect, it } from 'vitest'

import { GENERATED_TOOL_MAP } from '@/tools/generated'

describe('Generated email template tools', () => {
    const sendEmailSchema = GENERATED_TOOL_MAP['workflows-send-email']!().schema
    const hash = `v1:${'a'.repeat(64)}`

    it.each([
        ['a misspelled template field', { template: { key: 'welcome', content_hash: hash } }],
        ['an unknown top-level field', { template: { key: 'welcome', hash }, tempalte_key: 'welcome' }],
    ])('refuses a send with %s', (_case, input) => {
        expect(sendEmailSchema.safeParse({ to: 'jane@example.com', ...input }).success).toBe(false)
    })

    it('accepts a send by template key and hash', () => {
        const input = { to: 'jane@example.com', template: { key: 'welcome', hash }, message_data: { name: 'Jane' } }

        expect(sendEmailSchema.parse(input)).toEqual({ ...input, capture_engagement: true })
    })
})
