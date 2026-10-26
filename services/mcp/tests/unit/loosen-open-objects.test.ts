import { describe, expect, it } from 'vitest'

import { collectOpenObjectPaths, loosenOpenObjects } from '../../scripts/lib/loosen-open-objects.mjs'

const openObject = (properties: Record<string, unknown>): Record<string, unknown> => ({
    type: 'object',
    additionalProperties: true,
    properties,
})

const closedObject = (properties: Record<string, unknown>): Record<string, unknown> => ({
    type: 'object',
    properties,
})

const schemaWithBody = (body: Record<string, unknown>): Record<string, unknown> => ({
    paths: {
        '/things/': {
            post: {
                operationId: 'things_create',
                requestBody: { content: { 'application/json': { schema: body } } },
            },
        },
    },
})

const loosen = (body: Record<string, unknown>, source: string): string =>
    loosenOpenObjects(source, collectOpenObjectPaths(schemaWithBody(body), 'things'))

const designBody = closedObject({ design: openObject({ version: { type: 'integer' } }) })

describe('loosenOpenObjects', () => {
    it('loosens an open object under a nullable oneOf and keeps its closed sibling strict', () => {
        const body = closedObject({
            email: { oneOf: [designBody, { type: 'null' }] },
            sender: closedObject({ name: { type: 'string' } }),
        })
        const source = [
            'export const ThingsCreateBody = zod.strictObject({',
            '    email: zod.strictObject({ design: zod.strictObject({ version: zod.number() }) }).nullable(),',
            '    sender: zod.strictObject({ name: zod.string() }),',
            '})',
        ].join('\n')

        expect(loosen(body, source)).toBe(
            [
                'export const ThingsCreateBody = zod.strictObject({',
                '    email: zod.strictObject({ design: zod.looseObject({ version: zod.number() }) }).nullable(),',
                '    sender: zod.strictObject({ name: zod.string() }),',
                '})',
            ].join('\n')
        )
    })

    it.each([
        {
            case: 'the body export is missing',
            body: designBody,
            source: 'export const OtherBody = zod.strictObject({ design: zod.strictObject({ version: zod.number() }) })',
            error: /things things_create .*"design"/,
        },
        {
            case: 'the open object is hoisted into a const',
            body: designBody,
            source: [
                'const Design = zod.strictObject({ version: zod.number() })',
                'export const ThingsCreateBody = zod.strictObject({ design: Design })',
            ].join('\n'),
            error: /things things_create .*"design"/,
        },
        {
            case: 'the open object sits under items',
            body: closedObject({ entries: { type: 'array', items: openObject({ name: { type: 'string' } }) } }),
            source: 'export const ThingsCreateBody = zod.strictObject({ entries: zod.array(zod.strictObject({ name: zod.string() })) })',
            error: /things things_create .*"entries"/,
        },
        {
            case: 'the open object sits under oneOf',
            body: closedObject({
                data: { oneOf: [openObject({ a: { type: 'string' } }), closedObject({ a: { type: 'string' } })] },
            }),
            source: 'export const ThingsCreateBody = zod.strictObject({ data: zod.union([zod.strictObject({ a: zod.string() }), zod.strictObject({ a: zod.string() })]) })',
            error: /things things_create .*"data"/,
        },
        {
            case: 'two branches open the same path',
            body: {
                allOf: [
                    closedObject({ data: openObject({ a: { type: 'string' } }) }),
                    closedObject({ data: openObject({ b: { type: 'string' } }) }),
                ],
            },
            source: 'export const ThingsCreateBody = zod.strictObject({ data: zod.strictObject({ a: zod.string(), b: zod.string() }) })',
            error: /things things_create .*"data"/,
        },
        {
            case: 'a property name on the path has a dot',
            body: closedObject({ 'a.b': openObject({ c: { type: 'string' } }) }),
            source: "export const ThingsCreateBody = zod.strictObject({ 'a.b': zod.strictObject({ c: zod.string() }) })",
            error: /things things_create .*"a\.b"/,
        },
    ])('refuses to generate when $case', ({ body, source, error }) => {
        expect(() => loosen(body, source)).toThrow(error)
    })
})
