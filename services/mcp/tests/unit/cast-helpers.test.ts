/**
 * Unit tests for the narrow string→primitive casts used by
 * `param_overrides: { ...: { cast: '...' } }` in tools.yaml.
 *
 * The intent is to be permissive about the *one* shape LLM agents
 * commonly mis-emit (stringified integer ids) and strict about
 * everything else, so genuine type mismatches still surface as
 * honest zod rejections instead of silently casting to 0/1.
 */
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { castStringToInt } from '../../src/tools/cast-helpers'

describe('castStringToInt', () => {
    const schema = z.preprocess(castStringToInt, z.number().int())

    it('casts a stringified positive integer', () => {
        expect(schema.parse('123')).toBe(123)
    })

    it('casts a stringified negative integer', () => {
        expect(schema.parse('-7')).toBe(-7)
    })

    it('casts a string with leading zeros', () => {
        // Documented behavior: "007" → 7. Agents may include leading zeros
        // when extracting an id from text; we accept the obvious value.
        expect(schema.parse('007')).toBe(7)
    })

    it('passes through plain numbers untouched', () => {
        expect(schema.parse(42)).toBe(42)
    })

    it.each([
        ['boolean true', true],
        ['boolean false', false],
        ['null', null],
        ['empty array', []],
        ['empty string', ''],
        ['decimal string', '1.5'],
        ['hex string', '0x10'],
        ['non-numeric string', 'abc'],
        ['string with whitespace', ' 12 '],
    ] as const)('rejects non-int input: %s', (_label, input) => {
        // Anything that isn't a strict base-10 integer string passes through
        // to zod unchanged, which then rejects it with its honest type error.
        expect(() => schema.parse(input)).toThrow()
    })

    it('preserves the wrapped schema description and constraints', () => {
        const wrapped = z.preprocess(castStringToInt, z.number().int().min(1).describe('Experiment id.'))
        // Min constraint still applies after the cast runs.
        expect(() => wrapped.parse('0')).toThrow()
        expect(wrapped.parse('1')).toBe(1)
    })
})
