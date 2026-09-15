import { describe, expect, it } from 'vitest'

import { OrganizationsProjectsPartialUpdateBody } from '@/generated/core/api'

describe('project settings update logs schema', () => {
    const schema = OrganizationsProjectsPartialUpdateBody()

    it.each([
        ['', true],
        [' \t\n '.repeat(100), true],
        ['a'.repeat(200), true],
        [' \t' + 'a'.repeat(200) + '\n ', true],
        ['a'.repeat(201), false],
        [' \t' + 'a'.repeat(201) + '\n ', false],
        [' \t' + '😀'.repeat(200) + '\n ', true],
        [' \t' + '😀'.repeat(201) + '\n ', false],
        ['😀'.repeat(100) + 'a'.repeat(100), true],
        ['e\u0301'.repeat(100), true],
        ['e\u0301'.repeat(100) + 'a', false],
        ['\u001c\u001d\u001e\u001f\u0085' + '😀'.repeat(200) + '\u3000\u00a0', true],
        ['\ufeff' + 'a'.repeat(199), true],
        ['\ufeff' + 'a'.repeat(200), false],
        // Padding this long outruns the test timeout if the pattern can backtrack between padding and key.
        [' '.repeat(10000) + 'a'.repeat(201), false],
    ])('validates attribute key case %# after excluding surrounding whitespace', (key, accepted) => {
        const result = schema.safeParse({ logs_settings: { json_parse_logs_attribute_key: key } })
        expect(result.success).toBe(accepted)
    })

    it.each([14, 30, null])('accepts retention %s', (retention_days) => {
        expect(schema.parse({ logs_settings: { retention_days } }).logs_settings).toEqual({ retention_days })
    })

    it.each([7, 14.5, 90, '14'])('rejects retention %s', (retention_days) => {
        expect(schema.safeParse({ logs_settings: { retention_days } }).success).toBe(false)
    })

    it.each([null, {}, { json_parse_logs_attribute_key: ' app.context ', future_setting: { enabled: true } }])(
        'preserves clearing, omitted fields, and unknown settings: %j',
        (logs_settings) => {
            expect(schema.parse({ logs_settings }).logs_settings).toEqual(logs_settings)
        }
    )
})
