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

            expect(result.properties.filter!.hint).toBe(
                'DO NOT GUESS — you MUST run `schema my-tool filter` before populating this field'
            )
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

            expect(result.properties.series!.hint).toBe(
                'DO NOT GUESS — you MUST run `schema query-trends series` before populating this field'
            )
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

            expect(result.properties.nested!.hint).toBe(
                'DO NOT GUESS — you MUST run `schema my-tool parent.nested` before populating this field'
            )
        })

        // Regression: `schema query-trends series` resolves to an array-of-union node
        // that overflows the inline budget, so it gets summarized. The old summarizer
        // only walked `properties`, collapsing it to `{ type: 'array', properties: {} }`
        // and hiding every variant shape — forcing callers back to the prose examples.
        it('summarizes an array-of-union root by recursing into the item variants', () => {
            const schema = {
                type: 'array',
                items: {
                    anyOf: [
                        {
                            type: 'object',
                            title: 'EventsNode',
                            properties: { event: { type: 'string' }, math: { type: 'string' } },
                        },
                        {
                            type: 'object',
                            title: 'ActionsNode',
                            properties: { id: { type: 'number' } },
                        },
                    ],
                },
            }

            const result = summarizeSchema(schema, 'query-trends', 'series')

            expect(result.type).toBe('array')
            // Not an empty object summary anymore — the items shape is present.
            expect(result.items).not.toBeUndefined()
            expect(result.items!.type).toBe('union of 2 types (EventsNode, ActionsNode)')
            expect(result.items!.variants).toHaveLength(2)
            expect(result.items!.variants![0]!.properties.event).toEqual(expect.objectContaining({ type: 'string' }))
            expect(result.items!.variants![1]!.properties.id).toEqual(expect.objectContaining({ type: 'number' }))
        })

        // The `series.0` numeric-step workaround resolves to the bare union node; it
        // suffered the same empty-summary collapse.
        it('summarizes a union root into its variants', () => {
            const schema = {
                anyOf: [
                    { type: 'object', title: 'TypeA', properties: { a: { type: 'string' } } },
                    { type: 'object', title: 'TypeB', properties: { b: { type: 'number' } } },
                ],
            }

            const result = summarizeSchema(schema, 'my-tool', 'field.0')

            expect(result.type).toBe('union of 2 types (TypeA, TypeB)')
            expect(result.variants).toHaveLength(2)
            expect(result.variants![0]!.properties.a).toEqual(expect.objectContaining({ type: 'string' }))
        })

        // Array `items` and union variants don't consume a path segment, so a hint on a
        // field reached through them must still point at `<field>.<name>` for the
        // follow-up `schema` call to resolve.
        it('threads the original field path into hints through array/union unwrapping', () => {
            const schema = {
                type: 'array',
                items: {
                    anyOf: [
                        {
                            type: 'object',
                            properties: { props: { type: 'object', properties: { x: { type: 'string' } } } },
                        },
                    ],
                },
            }

            const result = summarizeSchema(schema, 'query-trends', 'series')

            expect(result.items!.properties.props!.hint).toBe(
                'DO NOT GUESS — you MUST run `schema query-trends series.props` before populating this field'
            )
        })

        // Zod discriminated unions (e.g. trends series) put variant identity in a `kind`
        // const, not a `title` — name them off that so the union header is legible.
        it('names union variants by a discriminator const when no title is present', () => {
            const schema = {
                anyOf: [
                    { type: 'object', properties: { kind: { type: 'string', const: 'EventsNode' } } },
                    { type: 'object', properties: { kind: { type: 'string', enum: ['ActionsNode'] } } },
                ],
            }

            const result = summarizeSchema(schema, 'query-trends', 'series.0')

            expect(result.type).toBe('union of 2 types (EventsNode, ActionsNode)')
        })

        it('collapses a nullable object union to the underlying object summary', () => {
            const schema = {
                anyOf: [{ type: 'object', properties: { a: { type: 'string' } } }, { type: 'null' }],
            }

            const result = summarizeSchema(schema, 'my-tool', 'maybeObj')

            expect(result.type).toBe('object')
            expect(result.variants).toBeUndefined()
            expect(result.properties.a).toEqual(expect.objectContaining({ type: 'string' }))
        })

        // Nullable-wrapper unwrapping recurses; a pathological chain must terminate via
        // the depth guard rather than blowing the stack on malformed input.
        it('terminates on a deeply nested chain of nullable wrappers', () => {
            let schema: Record<string, unknown> = { type: 'object', properties: { a: { type: 'string' } } }
            for (let i = 0; i < 100; i++) {
                schema = { anyOf: [schema, { type: 'null' }] }
            }

            expect(() => summarizeSchema(schema, 'my-tool', 'deep')).not.toThrow()
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

        describe('array of anyOf/oneOf items', () => {
            const arrayUnionSchema = {
                type: 'object',
                properties: {
                    series: {
                        type: 'array',
                        items: {
                            anyOf: [
                                {
                                    type: 'object',
                                    title: 'EventsNode',
                                    properties: {
                                        event: { type: 'string' },
                                        math: { type: 'string', enum: ['total', 'dau'] },
                                    },
                                },
                                {
                                    type: 'object',
                                    title: 'ActionsNode',
                                    properties: {
                                        id: { type: 'number' },
                                        math: { type: 'string', enum: ['total'] },
                                    },
                                },
                            ],
                        },
                    },
                },
            }

            it('resolves a named property that only exists on one variant', () => {
                expect(resolveSchemaPath(arrayUnionSchema, 'series.event')).toEqual({ type: 'string' })
            })

            it('resolves a named property that exists on multiple variants (first match wins)', () => {
                expect(resolveSchemaPath(arrayUnionSchema, 'series.math')).toEqual({
                    type: 'string',
                    enum: ['total', 'dau'],
                })
            })

            it('still supports the numeric-first workaround (series.0.event)', () => {
                expect(resolveSchemaPath(arrayUnionSchema, 'series.0.event')).toEqual({ type: 'string' })
                expect(resolveSchemaPath(arrayUnionSchema, 'series.1.id')).toEqual({ type: 'number' })
            })

            it('returns null when the property exists on no variant', () => {
                expect(resolveSchemaPath(arrayUnionSchema, 'series.nonexistent')).toBeNull()
            })

            it('supports oneOf in addition to anyOf', () => {
                const oneOfSchema = {
                    type: 'object',
                    properties: {
                        items: {
                            type: 'array',
                            items: {
                                oneOf: [{ type: 'object', properties: { foo: { type: 'string' } } }],
                            },
                        },
                    },
                }
                expect(resolveSchemaPath(oneOfSchema, 'items.foo')).toEqual({ type: 'string' })
            })
        })

        describe('composition walking (allOf + nesting)', () => {
            it('resolves a property defined via allOf (base + extension)', () => {
                const schema = {
                    type: 'object',
                    properties: {
                        filter: {
                            allOf: [
                                { type: 'object', properties: { base: { type: 'string' } } },
                                { type: 'object', properties: { extra: { type: 'number' } } },
                            ],
                        },
                    },
                }
                expect(resolveSchemaPath(schema, 'filter.base')).toEqual({ type: 'string' })
                expect(resolveSchemaPath(schema, 'filter.extra')).toEqual({ type: 'number' })
            })

            it('resolves a property on a top-level union variant', () => {
                const schema = {
                    anyOf: [
                        { type: 'object', title: 'A', properties: { foo: { type: 'string' } } },
                        { type: 'object', title: 'B', properties: { bar: { type: 'number' } } },
                    ],
                }
                expect(resolveSchemaPath(schema, 'foo')).toEqual({ type: 'string' })
                expect(resolveSchemaPath(schema, 'bar')).toEqual({ type: 'number' })
            })

            it('walks nested unions (anyOf of anyOf)', () => {
                const schema = {
                    type: 'object',
                    properties: {
                        node: {
                            anyOf: [
                                {
                                    anyOf: [
                                        { type: 'object', properties: { deep: { type: 'boolean' } } },
                                        { type: 'null' },
                                    ],
                                },
                                { type: 'object', properties: { other: { type: 'string' } } },
                            ],
                        },
                    },
                }
                expect(resolveSchemaPath(schema, 'node.deep')).toEqual({ type: 'boolean' })
                expect(resolveSchemaPath(schema, 'node.other')).toEqual({ type: 'string' })
            })

            it('walks array-of-union-of-allOf (arbitrary nesting)', () => {
                const schema = {
                    type: 'object',
                    properties: {
                        rows: {
                            type: 'array',
                            items: {
                                anyOf: [
                                    {
                                        allOf: [
                                            { type: 'object', properties: { id: { type: 'number' } } },
                                            { type: 'object', properties: { name: { type: 'string' } } },
                                        ],
                                    },
                                    { type: 'object', properties: { other: { type: 'boolean' } } },
                                ],
                            },
                        },
                    },
                }
                expect(resolveSchemaPath(schema, 'rows.id')).toEqual({ type: 'number' })
                expect(resolveSchemaPath(schema, 'rows.name')).toEqual({ type: 'string' })
                expect(resolveSchemaPath(schema, 'rows.other')).toEqual({ type: 'boolean' })
            })

            it('ignores tuple-form items (items as array) safely', () => {
                const schema = {
                    type: 'object',
                    properties: {
                        tuple: {
                            type: 'array',
                            items: [{ type: 'string' }, { type: 'number' }],
                        },
                    },
                }
                expect(resolveSchemaPath(schema, 'tuple.foo')).toBeNull()
                // Numeric index falls back to composition lookup, none exists on a tuple.
                expect(resolveSchemaPath(schema, 'tuple.0')).toBeNull()
            })

            it('blocks cycles via the seen set', () => {
                const schema: Record<string, unknown> = {
                    type: 'object',
                    properties: { foo: { type: 'string' } },
                }
                // self-reference through anyOf
                schema.anyOf = [schema]
                expect(() => resolveSchemaPath(schema, 'foo')).not.toThrow()
                expect(resolveSchemaPath(schema, 'foo')).toEqual({ type: 'string' })
                expect(resolveSchemaPath(schema, 'nonexistent')).toBeNull()
            })
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

            expect(listAvailablePaths(schema)).toEqual(['name', 'age'])
        })

        it('lists union variant indices with titles', () => {
            const schema = {
                anyOf: [
                    { type: 'object', title: 'TypeA' },
                    { type: 'object', title: 'TypeB' },
                ],
            }

            expect(listAvailablePaths(schema)).toEqual(['0 (TypeA)', '1 (TypeB)'])
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

            expect(listAvailablePaths(schema)).toEqual(['[items].event', '[items].math'])
        })

        it('lists array-of-anyOf variant properties with deduplication', () => {
            const schema = {
                type: 'array',
                items: {
                    anyOf: [
                        {
                            type: 'object',
                            title: 'EventsNode',
                            properties: { event: { type: 'string' }, math: { type: 'string' } },
                        },
                        {
                            type: 'object',
                            title: 'ActionsNode',
                            properties: { id: { type: 'number' }, math: { type: 'string' } },
                        },
                    ],
                },
            }

            const paths = listAvailablePaths(schema)
            expect(paths).toEqual(expect.arrayContaining(['[items].event', '[items].math', '[items].id']))
            // math appears on both variants but should only be listed once
            expect(paths.filter((p) => p === '[items].math')).toHaveLength(1)
        })

        it('lists properties reached through allOf composition', () => {
            const schema = {
                allOf: [
                    { type: 'object', properties: { base: { type: 'string' } } },
                    { type: 'object', properties: { extra: { type: 'number' } } },
                ],
            }
            const paths = listAvailablePaths(schema)
            expect(paths).toEqual(expect.arrayContaining(['base', 'extra']))
        })

        it('lists properties reached through top-level anyOf (with variant indices)', () => {
            const schema = {
                anyOf: [
                    { type: 'object', title: 'A', properties: { foo: { type: 'string' } } },
                    { type: 'object', title: 'B', properties: { bar: { type: 'number' } } },
                ],
            }
            const paths = listAvailablePaths(schema)
            expect(paths).toEqual(expect.arrayContaining(['foo', 'bar', '0 (A)', '1 (B)']))
        })
    })

    describe('TOKEN_CHAR_LIMIT', () => {
        it('is 48000 (8k tokens × 6 chars/token)', () => {
            expect(TOKEN_CHAR_LIMIT).toBe(48_000)
        })
    })
})
