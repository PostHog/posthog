import { beforeEach, describe, expect, it, vi } from 'vitest'

import { env } from '@/lib/env'
import { extractBearerToken, formatPrompt, redactToken, sanitizeHeaderValue } from '@/lib/utils'
import { omitResponseFields, pickResponseFields, withPostHogUrl } from '@/tools/tool-utils'
import type { Context } from '@/tools/types'

// Mock the env proxy that the production code reads through, rather than poking
// process.env — so the test exercises the same abstraction as extractBearerToken.
vi.mock('@/lib/env', () => ({ env: { NODE_ENV: undefined as string | undefined } }))

describe('utils', () => {
    describe('redactToken', () => {
        it('keeps only the last 4 chars and masks the rest', () => {
            expect(redactToken('phx_abcdefgh1234')).toBe('****1234')
        })

        it('fully masks tokens of 4 chars or fewer', () => {
            expect(redactToken('1234')).toBe('****')
            expect(redactToken('ab')).toBe('****')
        })

        it('fully masks an empty token', () => {
            expect(redactToken('')).toBe('****')
        })
    })

    describe('extractBearerToken', () => {
        beforeEach(() => {
            env.NODE_ENV = 'development'
        })

        const req = (opts: { header?: string; url?: string }): Request =>
            new Request(opts.url ?? 'https://mcp.posthog.com/', {
                headers: opts.header ? { Authorization: opts.header } : {},
            })

        it('prefers the Authorization bearer header', () => {
            expect(extractBearerToken(req({ header: 'Bearer phx_header', url: 'https://x/?token=phx_query' }))).toBe(
                'phx_header'
            )
        })

        it('falls back to the ?token query param in development', () => {
            expect(extractBearerToken(req({ url: 'https://x/?token=phx_query' }))).toBe('phx_query')
        })

        it('falls back to the ?token query param in test', () => {
            env.NODE_ENV = 'test'
            expect(extractBearerToken(req({ url: 'https://x/?token=phx_query' }))).toBe('phx_query')
        })

        it('ignores the ?token query param in production', () => {
            env.NODE_ENV = 'production'
            expect(extractBearerToken(req({ url: 'https://x/?token=phx_query' }))).toBeUndefined()
        })

        // Fail closed: an unset NODE_ENV (e.g. no Cloudflare Workers binding) must
        // not enable the query-param path.
        it('ignores the ?token query param when NODE_ENV is unset', () => {
            env.NODE_ENV = undefined
            expect(extractBearerToken(req({ url: 'https://x/?token=phx_query' }))).toBeUndefined()
        })

        it('still reads the header in production', () => {
            env.NODE_ENV = 'production'
            expect(extractBearerToken(req({ header: 'Bearer phx_header' }))).toBe('phx_header')
        })

        it('returns undefined when no token is present', () => {
            expect(extractBearerToken(req({}))).toBeUndefined()
        })
    })

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

        it('applies wildcards across dynamic object keys, skipping null values', () => {
            // Mirrors experiment-timeseries-results: `timeseries` is keyed by date strings
            // (not an array), so the exclude patterns must traverse object values to strip
            // the per-day compiled-query bloat while leaving the consumable stats intact.
            const obj = {
                status: 'partial',
                timeseries: {
                    '2024-01-01': { clickhouse_sql: 'SELECT ...', hogql: 'select ...', chance_to_win: 0.9 },
                    '2024-01-02': null,
                },
            }
            expect(omitResponseFields(obj, ['timeseries.*.clickhouse_sql', 'timeseries.*.hogql'])).toEqual({
                status: 'partial',
                timeseries: {
                    '2024-01-01': { chance_to_win: 0.9 },
                    '2024-01-02': null,
                },
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

        it('strips compiled HogQL artifacts from cohort filter conditions (cohorts-retrieve)', () => {
            const cohort = {
                id: 350280,
                name: 'sibling cohort',
                filters: {
                    properties: {
                        type: 'OR',
                        values: [
                            {
                                type: 'OR',
                                values: [
                                    {
                                        type: 'person',
                                        key: 'organization_id',
                                        operator: 'exact',
                                        value: ['uuid-a', 'uuid-b'],
                                        bytecode: ['_H', 1, 32, 'organization_id'],
                                        bytecode_error: null,
                                        conditionHash: '3fb4902b4bac10d2',
                                    },
                                ],
                            },
                        ],
                    },
                },
            }
            const paths = [
                'filters.properties.values.*.values.*.bytecode',
                'filters.properties.values.*.values.*.bytecode_error',
                'filters.properties.values.*.values.*.conditionHash',
                'filters.properties.values.*.bytecode',
                'filters.properties.values.*.bytecode_error',
                'filters.properties.values.*.conditionHash',
            ]
            expect(omitResponseFields(cohort, paths)).toEqual({
                id: 350280,
                name: 'sibling cohort',
                filters: {
                    properties: {
                        type: 'OR',
                        values: [
                            {
                                type: 'OR',
                                values: [
                                    {
                                        type: 'person',
                                        key: 'organization_id',
                                        operator: 'exact',
                                        value: ['uuid-a', 'uuid-b'],
                                    },
                                ],
                            },
                        ],
                    },
                },
            })
        })

        it('strips compiled artifacts from a single-level (flattened) cohort filter group', () => {
            const cohort = {
                filters: {
                    properties: {
                        type: 'AND',
                        values: [
                            {
                                type: 'behavioral',
                                key: 'signed up',
                                value: 'performed_event',
                                bytecode: ['_H', 1],
                                conditionHash: 'abc123',
                            },
                        ],
                    },
                },
            }
            const paths = [
                'filters.properties.values.*.values.*.bytecode',
                'filters.properties.values.*.values.*.bytecode_error',
                'filters.properties.values.*.values.*.conditionHash',
                'filters.properties.values.*.bytecode',
                'filters.properties.values.*.bytecode_error',
                'filters.properties.values.*.conditionHash',
            ]
            expect(omitResponseFields(cohort, paths)).toEqual({
                filters: {
                    properties: {
                        type: 'AND',
                        values: [{ type: 'behavioral', key: 'signed up', value: 'performed_event' }],
                    },
                },
            })
        })
    })

    describe('withPostHogUrl', () => {
        const context = {
            stateManager: { getProjectId: async () => 42 },
            api: { getProjectBaseUrl: (id: number) => `https://app/project/${id}` },
        } as unknown as Context

        it('adds _posthogUrl as a sibling field on an object result', async () => {
            const result = await withPostHogUrl(context, { id: 7, name: 'x' }, '/inbox/7')
            expect(result).toEqual({ id: 7, name: 'x', _posthogUrl: 'https://app/project/42/inbox/7' })
        })

        // Regression: spreading an array into an object (`{ ...arr }`) corrupts a raw-array
        // list response into `{ 0: …, 1: …, _posthogUrl: … }`. Arrays must be wrapped in
        // `{ results, _posthogUrl }` so they stay iterable for the agent.
        it('wraps a raw array result in { results, _posthogUrl }', async () => {
            const arr = [{ id: 1 }, { id: 2 }]
            const result = await withPostHogUrl(context, arr, '/inbox')
            expect(result).toEqual({ results: [{ id: 1 }, { id: 2 }], _posthogUrl: 'https://app/project/42/inbox' })
        })

        it('does not corrupt the array into numeric-keyed object fields', async () => {
            const result = await withPostHogUrl(context, [{ id: 1 }], '/inbox')
            expect(result).not.toHaveProperty('0')
            expect(Array.isArray((result as { results: unknown[] }).results)).toBe(true)
        })
    })
})
