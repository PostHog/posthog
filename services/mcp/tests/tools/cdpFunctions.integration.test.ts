import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/cdp_functions'
import type { Context } from '@/tools/types'

describe('Hog Functions', { concurrent: false }, () => {
    let context: Context
    const createdFunctionIds: string[] = []

    const listTool = GENERATED_TOOLS['cdp-functions-list']!()
    const createTool = GENERATED_TOOLS['cdp-functions-create']!()
    const retrieveTool = GENERATED_TOOLS['cdp-functions-retrieve']!()
    const partialUpdateTool = GENERATED_TOOLS['cdp-functions-partial-update']!()
    const deleteTool = GENERATED_TOOLS['cdp-functions-delete']!()
    const invocationsTool = GENERATED_TOOLS['cdp-functions-invocations-create']!()
    const rearrangeTool = GENERATED_TOOLS['cdp-functions-rearrange-partial-update']!()
    const logsTool = GENERATED_TOOLS['cdp-functions-logs-retrieve']!()
    const metricsTool = GENERATED_TOOLS['cdp-functions-metrics-retrieve']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        for (const id of createdFunctionIds) {
            try {
                await deleteTool.handler(context, { id })
            } catch {
                // best effort — function may already be deleted
            }
        }
        createdFunctionIds.length = 0
    })

    describe('cdp-functions-list tool', () => {
        it('should return paginated structure', async () => {
            const result = await listTool.handler(context, {})
            const data = parseToolResponse(result)

            expect(typeof data.count).toBe('number')
            expect(Array.isArray(data.results)).toBe(true)
            expect(typeof data._posthogUrl).toBe('string')
            expect(data._posthogUrl).toContain('/pipeline')
        })

        it('should respect the limit parameter', async () => {
            const result = await listTool.handler(context, { limit: 1 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(1)
        })

        it('should filter by type', async () => {
            const result = await listTool.handler(context, { type: 'destination' })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            for (const fn of data.results) {
                expect(fn.type).toBe('destination')
            }
        })
    })

    describe('cdp-functions-create tool', () => {
        it('should create a destination hog function', async () => {
            const params = {
                name: `test-fn-${generateUniqueKey('destination')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            }

            const result = await createTool.handler(context, params)
            const fn = parseToolResponse(result)
            createdFunctionIds.push(fn.id)

            expect(fn.id).toBeTruthy()
            expect(fn.name).toBe(params.name)
            expect(fn.type).toBe('destination')
            expect(fn.enabled).toBe(false)
        })

        it('should create a transformation hog function with execution_order', async () => {
            const params = {
                name: `test-fn-${generateUniqueKey('transformation')}`,
                type: 'transformation' as const,
                hog: 'return event',
                enabled: false,
                execution_order: 10,
            }

            const result = await createTool.handler(context, params)
            const fn = parseToolResponse(result)
            createdFunctionIds.push(fn.id)

            expect(fn.id).toBeTruthy()
            expect(fn.type).toBe('transformation')
            expect(fn.execution_order).toBe(10)
        })
    })

    describe('cdp-functions-retrieve tool', () => {
        it('should retrieve a specific hog function by ID', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('retrieve')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const createdFn = parseToolResponse(created)
            createdFunctionIds.push(createdFn.id)

            const result = await retrieveTool.handler(context, { id: createdFn.id })
            const fn = parseToolResponse(result)

            expect(fn.id).toBe(createdFn.id)
            expect(fn.name).toBe(createdFn.name)
            expect(fn.type).toBe('destination')
            expect(fn.hog).toBeTruthy()
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(retrieveTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('cdp-functions-partial-update tool', () => {
        it('should enable and disable a hog function', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('update')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const fn = parseToolResponse(created)
            createdFunctionIds.push(fn.id)

            // Enable it
            const enableResult = await partialUpdateTool.handler(context, { id: fn.id, enabled: true })
            const enabled = parseToolResponse(enableResult)
            expect(enabled.enabled).toBe(true)

            // Disable it again
            const disableResult = await partialUpdateTool.handler(context, { id: fn.id, enabled: false })
            const disabled = parseToolResponse(disableResult)
            expect(disabled.enabled).toBe(false)
        })

        it('should update the name of a hog function', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('rename')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const fn = parseToolResponse(created)
            createdFunctionIds.push(fn.id)

            const newName = `renamed-${generateUniqueKey('fn')}`
            const result = await partialUpdateTool.handler(context, { id: fn.id, name: newName })
            const updated = parseToolResponse(result)

            expect(updated.name).toBe(newName)
            expect(updated.id).toBe(fn.id)
        })

        it('should soft-delete a hog function via the delete tool', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('delete')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const fn = parseToolResponse(created)

            await deleteTool.handler(context, { id: fn.id })
            await expect(retrieveTool.handler(context, { id: fn.id })).rejects.toThrow()
        })
    })

    describe('cdp-functions-invocations-create tool', () => {
        // The tool schema correctly uses HogFunctionInvocationSerializer (configuration, globals, etc.).
        // This test verifies that omitting the required `configuration` field causes the backend to
        // reject the call with a 400, as expected.
        it('should reject an invocation with the generated schema (missing configuration)', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('invoke')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const fn = parseToolResponse(created)
            createdFunctionIds.push(fn.id)

            // The generated tool sends HogFunction body fields — Django rejects with 400
            // because `configuration` is required by HogFunctionInvocationSerializer.
            await expect(
                invocationsTool.handler(context, {
                    id: fn.id,
                    type: 'destination' as const,
                    hog: 'return null',
                })
            ).rejects.toThrow()
        })
    })

    describe('cdp-functions-rearrange-partial-update tool', () => {
        // The tool schema correctly includes the `orders` field from HogFunctionRearrangeSerializer.
        // This test verifies that omitting `orders` causes the backend to reject with 400
        // ("No orders provided"), as expected.
        it('should reject when called without orders (schema mismatch)', async () => {
            // Passing no fields produces an empty body — Django rejects with 400 "No orders provided"
            await expect(rearrangeTool.handler(context, {})).rejects.toThrow()
        })
    })

    describe('cdp-functions-logs-retrieve tool', () => {
        it('should return log entries for a function', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('logs')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const fn = parseToolResponse(created)
            createdFunctionIds.push(fn.id)

            const result = await logsTool.handler(context, { id: fn.id })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
        })

        it('should respect the limit parameter', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('logs-limit')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const fn = parseToolResponse(created)
            createdFunctionIds.push(fn.id)

            const result = await logsTool.handler(context, { id: fn.id, limit: 5 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(5)
        })

        it('should accept level filter', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('logs-level')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const fn = parseToolResponse(created)
            createdFunctionIds.push(fn.id)

            const result = await logsTool.handler(context, { id: fn.id, level: 'ERROR' })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(logsTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('cdp-functions-metrics-retrieve tool', () => {
        it('should return metrics for a function', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('metrics')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const fn = parseToolResponse(created)
            createdFunctionIds.push(fn.id)

            const result = await metricsTool.handler(context, { id: fn.id })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.labels)).toBe(true)
            expect(Array.isArray(data.series)).toBe(true)
        })

        it('should accept interval parameter', async () => {
            const created = await createTool.handler(context, {
                name: `test-fn-${generateUniqueKey('metrics-interval')}`,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const fn = parseToolResponse(created)
            createdFunctionIds.push(fn.id)

            const result = await metricsTool.handler(context, { id: fn.id, interval: 'day' })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.labels)).toBe(true)
            expect(Array.isArray(data.series)).toBe(true)
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(metricsTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('Hog Functions workflow', () => {
        it('should support a full create → retrieve → update → delete lifecycle', async () => {
            const name = `workflow-fn-${generateUniqueKey('lifecycle')}`

            // Create
            const createResult = await createTool.handler(context, {
                name,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const created = parseToolResponse(createResult)
            expect(created.id).toBeTruthy()
            expect(created.name).toBe(name)

            // Retrieve
            const retrieveResult = await retrieveTool.handler(context, { id: created.id })
            const retrieved = parseToolResponse(retrieveResult)
            expect(retrieved.id).toBe(created.id)

            // Update
            const updatedName = `${name}-updated`
            const updateResult = await partialUpdateTool.handler(context, {
                id: created.id,
                name: updatedName,
                enabled: true,
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.name).toBe(updatedName)
            expect(updated.enabled).toBe(true)

            // Delete
            await deleteTool.handler(context, { id: created.id })
            await expect(retrieveTool.handler(context, { id: created.id })).rejects.toThrow()
        })

        it('should appear in list results after creation', async () => {
            const name = `list-check-fn-${generateUniqueKey('appear')}`

            const createResult = await createTool.handler(context, {
                name,
                type: 'destination' as const,
                hog: 'return null',
                enabled: false,
            })
            const created = parseToolResponse(createResult)
            createdFunctionIds.push(created.id)

            const listResult = await listTool.handler(context, { type: 'destination' })
            const data = parseToolResponse(listResult)

            const found = data.results.find((fn: any) => fn.id === created.id)
            expect(found).toBeTruthy()
            expect(found.name).toBe(name)
        })
    })
})
