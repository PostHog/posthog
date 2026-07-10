import { describe, expect, it } from 'vitest'

import {
    TOKEN_CHAR_LIMIT,
    budgetSchemaFields,
    expandSchemaPathPattern,
    listAvailablePaths,
    resolveSchemaPath,
    type SchemaFieldEntry,
    summarizeSchema,
} from '../../src/tools/schema-utils'

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

    describe('expandSchemaPathPattern', () => {
        const schema = {
            type: 'object',
            properties: {
                name: { type: 'string' },
                filter: { type: 'object', properties: { key: { type: 'string' }, value: { type: 'number' } } },
                grouped: {
                    type: 'object',
                    properties: {
                        x: { type: 'object', properties: { c: { type: 'string' }, d: { type: 'number' } } },
                        y: { type: 'object', properties: { c: { type: 'boolean' } } },
                    },
                },
                series: {
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
                },
            },
        }

        // A literal (glob-free) pattern must resolve to exactly the node
        // resolveSchemaPath returns — they share first-match-wins traversal, so a
        // divergence here would silently return a different schema than the drill-down.
        it.each(['name', 'filter.key', 'series.event', 'series.math'])(
            'matches resolveSchemaPath for the literal path %s',
            (path) => {
                const expansion = expandSchemaPathPattern(schema, path, 25)
                expect(expansion.truncated).toBe(false)
                expect(expansion.matches).toHaveLength(1)
                expect(expansion.matches[0]!.path).toBe(path)
                expect(expansion.matches[0]!.schema).toEqual(resolveSchemaPath(schema, path))
            }
        )

        // A glob segment enumerates the resolvable child names of each frontier node,
        // including through array items and union variants, deduped across variants.
        it.each([
            ['mid-path glob', 'grouped.*.c', ['grouped.x.c', 'grouped.y.c']],
            ['object glob', 'filter.*', ['filter.key', 'filter.value']],
            ['array-of-union glob (dedupes shared props)', 'series.*', ['series.event', 'series.math', 'series.id']],
        ])('expands the %s pattern to its concrete paths', (_label, pattern, expected) => {
            const expansion = expandSchemaPathPattern(schema, pattern, 25)
            expect(expansion.truncated).toBe(false)
            // Sorted set equality: a missing dedupe would surface as a duplicate path.
            expect(expansion.matches.map((m) => m.path).sort()).toEqual([...expected].sort())
        })

        it('reports available names from the failing depth, not the root, on a zero match', () => {
            const expansion = expandSchemaPathPattern(schema, 'filter.nope', 25)
            expect(expansion.matches).toEqual([])
            // Names come from `filter` (where the walk stopped), not the root's fields.
            expect(expansion.available!.sort()).toEqual(['key', 'value'])
            expect(expansion.available).not.toContain('name')
            expect(expansion.available).not.toContain('series')
        })

        // A JSON Schema object with `count` scalar props plus one `zz` object
        // holding an `event` child, with `zz` enumerated LAST — the shape that
        // used to lose `zz` to premature per-segment truncation.
        function wideSchema(count: number): Record<string, unknown> {
            const properties: Record<string, unknown> = {}
            for (let i = 0; i < count; i++) {
                properties[`a${i}`] = { type: 'string' }
            }
            properties.zz = { type: 'object', properties: { event: { type: 'string' } } }
            return { type: 'object', properties }
        }

        // The `limit` cap must apply to the FINAL matches only: a mid-pattern
        // frontier wider than `limit` used to be cut before later segments could
        // filter it, silently dropping reachable paths AND flagging `truncated`
        // on results that were actually complete.
        it('keeps a wide intermediate frontier alive so later segments can filter it, without a bogus truncated flag', () => {
            const expansion = expandSchemaPathPattern(wideSchema(30), '*.event', 25)
            expect(expansion.matches.map((m) => m.path)).toEqual(['zz.event'])
            expect(expansion.truncated).toBe(false)
        })

        it('caps only the final matches at the limit and flags truncation', () => {
            const expansion = expandSchemaPathPattern(wideSchema(30), '*', 25)
            expect(expansion.matches).toHaveLength(25)
            expect(expansion.truncated).toBe(true)
        })

        it('clamps the available list on a zero match so error entries stay small', () => {
            const expansion = expandSchemaPathPattern(wideSchema(60), 'nope', 25)
            expect(expansion.matches).toEqual([])
            expect(expansion.available).toHaveLength(50)
        })

        // All-digit property names are ambiguous: literal resolution tries the
        // index first (`findIndexedChild`), so glob emission must bind the same
        // way or an emitted path would re-resolve to a different node.
        it('binds glob-matched all-digit names to the node a literal re-resolution returns', () => {
            const quirky = {
                type: 'object',
                properties: {
                    parent: {
                        anyOf: [
                            { type: 'object', properties: { '0': { type: 'string' }, other: { type: 'number' } } },
                            { type: 'array', items: { type: 'boolean' } },
                        ],
                    },
                },
            }
            const expansion = expandSchemaPathPattern(quirky, 'parent.*', 25)
            expect(expansion.matches.length).toBeGreaterThan(0)
            for (const match of expansion.matches) {
                expect(resolveSchemaPath(quirky, match.path)).toBe(match.schema)
            }
        })
    })

    describe('budgetSchemaFields', () => {
        const TOOL = 'mock-tool'

        // Full JSON Schema overflows, but the summary is far smaller: each group
        // collapses to a name list + hint instead of its full inner shape. That gap
        // is exactly what the degrade ladder trades on.
        function nestedObject(groups: number): Record<string, unknown> {
            const properties: Record<string, unknown> = {}
            for (let g = 0; g < groups; g++) {
                const inner: Record<string, unknown> = {}
                for (let i = 0; i < 20; i++) {
                    inner[`inner_${i}`] = { type: 'string', description: 'padding padding padding padding' }
                }
                properties[`group_${g}`] = { type: 'object', properties: inner }
            }
            return { type: 'object', properties }
        }

        const entryLen = (entry: SchemaFieldEntry): number => JSON.stringify(entry).length
        const combinedLen = (entries: SchemaFieldEntry[]): number =>
            entries.reduce((sum, entry) => sum + entryLen(entry), 0) + Math.max(0, entries.length - 1)
        const summaryLen = (field: string, schema: Record<string, unknown>): number =>
            entryLen({ field, schema: summarizeSchema(schema, TOOL, field) })

        const smallA: SchemaFieldEntry = {
            field: 'a',
            schema: { type: 'object', properties: { x: { type: 'string' } } },
        }
        const smallB: SchemaFieldEntry = {
            field: 'b',
            schema: { type: 'object', properties: { y: { type: 'number' } } },
        }
        const bigA = nestedObject(60)
        const bigB = nestedObject(90)
        const errorEntry: SchemaFieldEntry = {
            field: 'bad',
            error: 'Unknown path "bad"',
            available: Array.from({ length: 60 }, (_, i) => `name_${i}`),
        }

        // Each case pins one rung of the degrade ladder. `states[i]` is the expected
        // final state of entry i: full (schema untouched), summary, stub, or error.
        const cases: Array<{ label: string; entries: SchemaFieldEntry[]; budget: number; states: string[] }> = [
            {
                label: 'all entries fit so all stay full',
                entries: [smallA, smallB],
                budget: TOKEN_CHAR_LIMIT,
                states: ['full', 'full'],
            },
            {
                label: 'one oversized entry is summarized while its small sibling stays full',
                entries: [{ field: 'big', schema: bigA }, smallA],
                budget: summaryLen('big', bigA) + entryLen(smallA) + 1,
                states: ['summary', 'full'],
            },
            {
                label: 'summaries that still overflow degrade the largest to a stub',
                entries: [
                    { field: 'bigA', schema: bigA },
                    { field: 'bigB', schema: bigB },
                ],
                budget: summaryLen('bigA', bigA) + 250,
                states: ['summary', 'stub'],
            },
            {
                label: 'an error entry passes through untouched and counts toward the total',
                entries: [errorEntry, { field: 'big', schema: bigA }],
                budget: entryLen(errorEntry) + summaryLen('big', bigA) + 1,
                states: ['error', 'summary'],
            },
        ]

        // Derives an entry's final ladder state from the output alone (vs its input),
        // folding the stub-hint check into the state so one array-equality assertion
        // covers every entry — a mismatched hint surfaces as `stub-bad-hint`.
        const classify = (out: SchemaFieldEntry, input: SchemaFieldEntry): string => {
            if ('error' in out) {
                return 'error'
            }
            if ('hint' in out) {
                return /run `schema mock-tool \w+` alone/.test(out.hint) ? 'stub' : 'stub-bad-hint'
            }
            return JSON.stringify(out.schema) === JSON.stringify((input as { schema: unknown }).schema)
                ? 'full'
                : 'summary'
        }

        it.each(cases)('$label', ({ entries, budget, states }) => {
            const result = budgetSchemaFields(entries, TOOL, budget)
            expect(result.map((out, i) => classify(out, entries[i]!))).toEqual(states)
            expect(combinedLen(result)).toBeLessThanOrEqual(budget)
        })
    })

    describe('TOKEN_CHAR_LIMIT', () => {
        it('is 48000 (8k tokens × 6 chars/token)', () => {
            expect(TOKEN_CHAR_LIMIT).toBe(48_000)
        })
    })
})
