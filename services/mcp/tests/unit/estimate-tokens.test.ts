import { describe, expect, it } from 'vitest'

import { estimateTokens } from '@/lib/estimate-tokens'

describe('estimateTokens', () => {
    const cases: Array<[string, unknown, number]> = [
        ['null', null, 0],
        ['undefined', undefined, 0],
        ['empty string', '', 0],
        ['4-char string', 'abcd', 1],
        ['5-char string rounds up', 'abcde', 2],
        ['empty object', {}, 1],
        ['serialized object', { a: 'x' }, 3],
        ['number', 1234, 1],
    ]

    it.each(cases)('estimates %s', (_label, value, expected) => {
        expect(estimateTokens(value)).toBe(expected)
    })

    it('returns 0 for non-serializable values instead of throwing', () => {
        const circular: Record<string, unknown> = {}
        circular.self = circular
        expect(estimateTokens(circular)).toBe(0)
        expect(estimateTokens(10n)).toBe(0)
    })
})
