import { describe, expect, it } from 'vitest'

import { formatPrompt, sanitizeHeaderValue } from '@/lib/utils'
import { omitResponseFields, pickResponseFields } from '@/tools/tool-utils'

describe('utils', () => {
    describe('formatPrompt', () => {
        it('substitutes placeholders with values', () => {
            expect(formatPrompt('Hello {name}, welcome to {place}', { name: 'world', place: 'earth' })).toBe(
                'Hello world, welcome to earth'
            )
        })

        it('replaces all occurrences of a placeholder', () => {
            expect(formatPrompt('{x} and {x} again', { x: 'A' })).toBe('A and A again')
        })

        it('trims the final output', () => {
            expect(formatPrompt('  {x}  ', { x: 'A' })).toBe('A')
        })

        it('leaves unknown placeholders untouched', () => {
            expect(formatPrompt('{known} {unknown}', { known: 'yes' })).toBe('yes {unknown}')
        })

        // Regression: String.prototype.replaceAll with a string replacement interprets
        // $ escape sequences ($&, $$, $`, $'). Values from guidelines.md contain `$`
        // (e.g. `$pageview`) and would splice the template prefix/suffix into the output.
        // Using a function replacement bypasses $ interpretation.
        it('treats $ sequences in values as literal text (regression)', () => {
            expect(formatPrompt('PREFIX {v} SUFFIX', { v: '`$`' })).toBe('PREFIX `$` SUFFIX')
            expect(formatPrompt('PREFIX {v} SUFFIX', { v: 'price is $5 and $$10' })).toBe(
                'PREFIX price is $5 and $$10 SUFFIX'
            )
            expect(formatPrompt('PREFIX {v} SUFFIX', { v: '$& $`' })).toBe('PREFIX $& $` SUFFIX')
            expect(formatPrompt('PREFIX {v} SUFFIX', { v: "$'" })).toBe("PREFIX $' SUFFIX")
        })

        it('does not splice the template prefix when a value contains $` (realistic PostHog case)', () => {
            const template = 'Header text before {guidelines} and trailing bit'
            const guidelinesValue = 'Events start with `$` (e.g., `$pageview`)'
            expect(formatPrompt(template, { guidelines: guidelinesValue })).toBe(
                'Header text before Events start with `$` (e.g., `$pageview`) and trailing bit'
            )
        })
    })

    describe('sanitizeHeaderValue', () => {
        it.each([
            ['passthrough', 'posthog/wizard 1.0', 'posthog/wizard 1.0'],
            ['strips control chars', 'agent\x00with\x1fnulls', 'agentwithnulls'],
            ['strips DEL character', 'hello\x7fworld', 'helloworld'],
            ['truncates to max length', 'a'.repeat(1500), 'a'.repeat(1000)],
            ['trims whitespace', '  spaces  ', 'spaces'],
            ['strips then trims', '\x00  hello  \x1f', 'hello'],
            ['whitespace only is undefined', ' ', undefined],
            ['undefined is undefined', undefined, undefined],
        ])('%s', (_name, input, expected) => {
            expect(sanitizeHeaderValue(input)).toBe(expected)
        })
    })

    describe('pickResponseFields', () => {
        it('keeps only specified top-level fields', () => {
            const obj = { id: 1, name: 'test', filters: { a: 1 }, created_by: 'user' }
            expect(pickResponseFields(obj, ['id', 'name'])).toEqual({ id: 1, name: 'test' })
        })

        it('handles missing fields gracefully', () => {
            const obj = { id: 1, name: 'test' }
            expect(pickResponseFields(obj, ['id', 'nonexistent'])).toEqual({ id: 1 })
        })

        it('supports nested dot-paths without wildcards', () => {
            const obj = { filters: { groups: [1, 2] }, name: 'flag' }
            expect(pickResponseFields(obj, ['filters.groups'])).toEqual({ filters: { groups: [1, 2] } })
        })

        it('supports wildcard dot-path patterns on arrays', () => {
            const obj = {
                groups: [
                    { key: 'a', properties: [1, 2], extra: 'x' },
                    { key: 'b', properties: [3], extra: 'y' },
                ],
            }
            expect(pickResponseFields(obj, ['groups.*.key'])).toEqual({
                groups: [{ key: 'a' }, { key: 'b' }],
            })
        })

        it('combines multiple paths including wildcards', () => {
            const obj = {
                id: 1,
                name: 'flag',
                groups: [
                    { key: 'a', props: [1], extra: 'x' },
                    { key: 'b', props: [2], extra: 'y' },
                ],
            }
            expect(pickResponseFields(obj, ['id', 'groups.*.key'])).toEqual({
                id: 1,
                groups: [{ key: 'a' }, { key: 'b' }],
            })
        })

        it('handles deeply nested wildcards', () => {
            const obj = {
                a: [
                    {
                        b: [
                            { c: 1, d: 2 },
                            { c: 3, d: 4 },
                        ],
                    },
                    { b: [{ c: 5, d: 6 }] },
                ],
            }
            expect(pickResponseFields(obj, ['a.*.b.*.c'])).toEqual({
                a: [{ b: [{ c: 1 }, { c: 3 }] }, { b: [{ c: 5 }] }],
            })
        })

        it('handles null values in the tree', () => {
            const obj = { id: 1, nested: null, name: 'test' }
            expect(pickResponseFields(obj, ['id', 'nested.foo'])).toEqual({ id: 1 })
        })

        it('handles empty arrays', () => {
            const obj = { groups: [] }
            expect(pickResponseFields(obj, ['groups.*.key'])).toEqual({ groups: [] })
        })

        it('does not mutate the original object', () => {
            const obj = { id: 1, name: 'test', extra: 'data' }
            pickResponseFields(obj, ['id'])
            expect(obj).toEqual({ id: 1, name: 'test', extra: 'data' })
        })
    })

    describe('omitResponseFields', () => {
        it('removes specified top-level fields', () => {
            const obj = { id: 1, name: 'test', filters: { a: 1 }, created_by: 'user' }
            expect(omitResponseFields(obj, ['filters', 'created_by'])).toEqual({ id: 1, name: 'test' })
        })

        it('handles missing fields gracefully', () => {
            const obj = { id: 1, name: 'test' }
            expect(omitResponseFields(obj, ['nonexistent'])).toEqual({ id: 1, name: 'test' })
        })

        it('supports nested dot-paths without wildcards', () => {
            const obj = { filters: { groups: [1], extra: true }, name: 'flag' }
            expect(omitResponseFields(obj, ['filters.groups'])).toEqual({ filters: { extra: true }, name: 'flag' })
        })

        it('supports wildcard dot-path patterns on arrays', () => {
            const obj = {
                groups: [
                    { key: 'a', properties: [1, 2], extra: 'x' },
                    { key: 'b', properties: [3], extra: 'y' },
                ],
            }
            expect(omitResponseFields(obj, ['groups.*.properties'])).toEqual({
                groups: [
                    { key: 'a', extra: 'x' },
                    { key: 'b', extra: 'y' },
                ],
            })
        })

        it('removes multiple paths at once', () => {
            const obj = { id: 1, name: 'test', filters: { a: 1 }, tags: ['x'] }
            expect(omitResponseFields(obj, ['filters', 'tags'])).toEqual({ id: 1, name: 'test' })
        })

        it('handles deeply nested wildcards', () => {
            const obj = {
                a: [
                    {
                        b: [
                            { c: 1, d: 2 },
                            { c: 3, d: 4 },
                        ],
                    },
                    { b: [{ c: 5, d: 6 }] },
                ],
            }
            expect(omitResponseFields(obj, ['a.*.b.*.d'])).toEqual({
                a: [{ b: [{ c: 1 }, { c: 3 }] }, { b: [{ c: 5 }] }],
            })
        })

        it('handles null values in the tree', () => {
            const obj = { id: 1, nested: null }
            expect(omitResponseFields(obj, ['nested.foo'])).toEqual({ id: 1, nested: null })
        })

        it('handles empty arrays', () => {
            const obj = { groups: [] }
            expect(omitResponseFields(obj, ['groups.*.key'])).toEqual({ groups: [] })
        })

        it('does not mutate the original object', () => {
            const obj = { id: 1, name: 'test', extra: { nested: true } }
            omitResponseFields(obj, ['extra'])
            expect(obj).toEqual({ id: 1, name: 'test', extra: { nested: true } })
        })
    })
})
