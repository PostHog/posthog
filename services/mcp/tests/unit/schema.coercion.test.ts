import { describe, expect, it } from 'vitest'

import { preprocessParams } from '@/lib/preprocessParams'
import {
    ExperimentDeleteSchema,
    ExperimentGetSchema,
    ExperimentResultsGetSchema,
    ExperimentUpdateSchema,
    DashboardDeleteSchema,
    DashboardGetSchema,
    ActionDeleteSchema,
    ActionGetSchema,
} from '@/schema/tool-inputs'

describe('MCP tool input coercion', () => {
    describe('numeric ID coercion', () => {
        it.each([
            ['ExperimentGetSchema', ExperimentGetSchema, { experimentId: '74850' }],
            ['ExperimentDeleteSchema', ExperimentDeleteSchema, { experimentId: '74850' }],
            ['ExperimentResultsGetSchema', ExperimentResultsGetSchema, { experimentId: '74850', refresh: true }],
            ['DashboardDeleteSchema', DashboardDeleteSchema, { dashboardId: '42' }],
            ['DashboardGetSchema', DashboardGetSchema, { dashboardId: '42' }],
            ['ActionDeleteSchema', ActionDeleteSchema, { actionId: '99' }],
            ['ActionGetSchema', ActionGetSchema, { actionId: '99' }],
        ])('%s accepts string-encoded numeric IDs', (_name, schema, input) => {
            const result = schema.safeParse(input)
            expect(result.success).toBe(true)
        })

        it.each([
            ['ExperimentGetSchema', ExperimentGetSchema, { experimentId: 74850 }],
            ['DashboardDeleteSchema', DashboardDeleteSchema, { dashboardId: 42 }],
            ['ActionGetSchema', ActionGetSchema, { actionId: 99 }],
        ])('%s still accepts proper numeric IDs', (_name, schema, input) => {
            const result = schema.safeParse(input)
            expect(result.success).toBe(true)
        })

        it('rejects non-numeric strings', () => {
            const result = ExperimentGetSchema.safeParse({ experimentId: 'abc' })
            expect(result.success).toBe(false)
        })
    })

    describe('preprocessParams JSON string coercion', () => {
        it('parses JSON-string objects into objects', () => {
            const result = preprocessParams({
                experimentId: '74850',
                data: '{"name":"Test experiment"}',
            })
            expect(result).toEqual({
                experimentId: '74850',
                data: { name: 'Test experiment' },
            })
        })

        it('parses JSON-string arrays into arrays', () => {
            const result = preprocessParams({
                ids: '[1, 2, 3]',
            })
            expect(result).toEqual({ ids: [1, 2, 3] })
        })

        it('leaves non-JSON strings unchanged', () => {
            const result = preprocessParams({
                name: 'hello world',
                experimentId: '74850',
            })
            expect(result).toEqual({
                name: 'hello world',
                experimentId: '74850',
            })
        })

        it('leaves invalid JSON strings unchanged', () => {
            const result = preprocessParams({
                data: '{invalid json}',
            })
            expect(result).toEqual({ data: '{invalid json}' })
        })

        it('leaves non-string values unchanged', () => {
            const result = preprocessParams({
                experimentId: 123,
                data: { name: 'already an object' },
                enabled: true,
            })
            expect(result).toEqual({
                experimentId: 123,
                data: { name: 'already an object' },
                enabled: true,
            })
        })
    })

    describe('nested object coercion via ExperimentUpdateSchema', () => {
        it('accepts data as an inline object', () => {
            const result = ExperimentUpdateSchema.safeParse({
                experimentId: 123,
                data: { name: 'Test experiment' },
            })
            expect(result.success).toBe(true)
        })

        it('accepts experimentId as string with inline data object', () => {
            const result = ExperimentUpdateSchema.safeParse({
                experimentId: '123',
                data: { name: 'Test experiment' },
            })
            expect(result.success).toBe(true)
            if (result.success) {
                expect(result.data.experimentId).toBe(123)
            }
        })

        it('accepts experimentId as string with JSON-stringified data object', () => {
            const preprocessed = preprocessParams({
                experimentId: '123',
                data: '{"name":"Test experiment"}',
            })
            const result = ExperimentUpdateSchema.safeParse(preprocessed)
            expect(result.success).toBe(true)
            if (result.success) {
                expect(result.data.experimentId).toBe(123)
                expect(result.data.data).toEqual({ name: 'Test experiment' })
            }
        })
    })
})
