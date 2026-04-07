import { describe, expect, it } from 'vitest'

import { TOKEN_CHAR_LIMIT, listAvailablePaths, resolveSchemaPath, summarizeSchema } from '../../src/tools/schema-utils'

describe('schema-utils', () => {
    describe('summarizeSchema', () => {
        it('summarizes simple scalar fields without hints', () => {
            const schema = {
                type: 'object',
                required: ['name'],
                properties: {
                    name: { type: 'string', description: 'The name' },
                    count: { type: 'number', default: 10 },
                    status: { type: 'string', enum: ['active', 'inactive'] },
                },
            }

            const result = summarizeSchema(schema, 'my-tool')

            expect(result.type).toBe('object')
            expect(result.required).toEqual(['name'])
            expect(result.properties.name).toEqual({
                type: 'string',
                description: 'The name',
                required: true,
            })
            expect(result.properties.count).toEqual({
                type: 'number',
                default: 10,
            })
            expect(result.properties.status).toEqual({
                type: 'string',
                enum: ['active', 'inactive'],
            })
            // No hints on simple fields
            expect(result.properties.name!.hint).toBeUndefined()
            expect(result.properties.count!.hint).toBeUndefined()
            expect(result.properties.status!.hint).toBeUndefined()
        })

        it('adds hints for object fields with properties', () => {
            const schema = {
                type: 'object',
                properties: {
                    filter: {
                        type: 'object',
                        description: 'Filter config',
                        properties: {
                            key: { type: 'string' },
                            value: { type: 'string' },
                        },
                    },
                },
            }

            const result = summarizeSchema(schema, 'my-tool')

            expect(result.properties.filter!.hint).toBe('Run `schema my-tool filter` for full structure')
            expect(result.properties.filter!.fields).toEqual(['key', 'value'])
        })

        it('adds hints for arrays with complex items', () => {
            const schema = {
                type: 'object',
                properties: {
                    series: {
                        type: 'array',
                        description: 'Series list',
                        items: {
                            anyOf: [
                                {
                                    type: 'object',
                                    title: 'EventsNode',
                                    properties: { event: { type: 'string' } },
                                },
                                {
                                    type: 'object',
                                    title: 'ActionsNode',
                                    properties: { id: { type: 'number' } },
                                },
                            ],
                        },
                    },
                },
            }

            const result = summarizeSchema(schema, 'query-trends')

            expect(result.properties.series!.hint).toBe('Run `schema query-trends series` for full structure')
            expect(result.properties.series!.items).toBe('union of 2 types (EventsNode, ActionsNode)')
        })

        it('does not add hints for arrays with simple items', () => {
            const schema = {
                type: 'object',
                properties: {
                    tags: {
                        type: 'array',
                        items: { type: 'string' },
                    },
                },
            }

            const result = summarizeSchema(schema, 'my-tool')

            expect(result.properties.tags!.hint).toBeUndefined()
            expect(result.properties.tags!.items).toBe('string')
        })

        it('does not add hints for nullable scalar unions', () => {
            const schema = {
                type: 'object',
                properties: {
                    name: {
                        anyOf: [{ type: 'string' }, { type: 'null' }],
                    },
                },
            }

            const result = summarizeSchema(schema, 'my-tool')

            expect(result.properties.name!.hint).toBeUndefined()
        })

        it('includes fieldPath in hints when provided', () => {
            const schema = {
                type: 'object',
                properties: {
                    nested: {
                        type: 'object',
                        properties: {
                            deep: { type: 'string' },
                        },
                    },
                },
            }

            const result = summarizeSchema(schema, 'my-tool', 'parent')

            expect(result.properties.nested!.hint).toBe('Run `schema my-tool parent.nested` for full structure')
        })
    })

    describe('resolveSchemaPath', () => {
        const schema = {
            type: 'object',
            properties: {
                name: { type: 'string' },
                filter: {
                    type: 'object',
                    properties: {
                        key: { type: 'string' },
                        value: { type: 'number' },
                    },
                },
                series: {
                    type: 'array',
                    items: {
                        type: 'object',
                        properties: {
                            event: { type: 'string' },
                            math: { type: 'string', enum: ['total', 'dau'] },
                        },
                    },
                },
                variant: {
                    anyOf: [
                        {
                            type: 'object',
                            title: 'TypeA',
                            properties: { a: { type: 'string' } },
                        },
                        {
                            type: 'object',
                            title: 'TypeB',
                            properties: { b: { type: 'number' } },
                        },
                    ],
                },
            },
        }

        it('resolves top-level properties', () => {
            expect(resolveSchemaPath(schema, 'name')).toEqual({ type: 'string' })
        })

        it('resolves nested object properties via dot path', () => {
            expect(resolveSchemaPath(schema, 'filter.key')).toEqual({
                type: 'string',
            })
        })

        it('resolves array item properties', () => {
            expect(resolveSchemaPath(schema, 'series.event')).toEqual({
                type: 'string',
            })
        })

        it('resolves union variants by index', () => {
            expect(resolveSchemaPath(schema, 'variant.0')).toEqual({
                type: 'object',
                title: 'TypeA',
                properties: { a: { type: 'string' } },
            })
        })

        it('returns null for invalid paths', () => {
            expect(resolveSchemaPath(schema, 'nonexistent')).toBeNull()
            expect(resolveSchemaPath(schema, 'filter.nonexistent')).toBeNull()
        })
    })

    describe('listAvailablePaths', () => {
        it('lists property names for objects', () => {
            const schema = {
                type: 'object',
                properties: {
                    name: { type: 'string' },
                    age: { type: 'number' },
                },
            }

            expect(listAvailablePaths(schema, '')).toEqual(['name', 'age'])
        })

        it('lists union variant indices with titles', () => {
            const schema = {
                anyOf: [
                    { type: 'object', title: 'TypeA' },
                    { type: 'object', title: 'TypeB' },
                ],
            }

            expect(listAvailablePaths(schema, '')).toEqual(['0 (TypeA)', '1 (TypeB)'])
        })

        it('lists array item properties', () => {
            const schema = {
                type: 'array',
                items: {
                    type: 'object',
                    properties: {
                        event: { type: 'string' },
                        math: { type: 'string' },
                    },
                },
            }

            expect(listAvailablePaths(schema, '')).toEqual(['[items].event', '[items].math'])
        })
    })

    describe('TOKEN_CHAR_LIMIT', () => {
        it('is 96000 (16k tokens × 6 chars/token)', () => {
            expect(TOKEN_CHAR_LIMIT).toBe(96_000)
        })
    })
})
