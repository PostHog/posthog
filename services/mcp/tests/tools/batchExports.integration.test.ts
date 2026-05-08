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
import { GENERATED_TOOLS } from '@/tools/generated/batch_exports'
import type { Context } from '@/tools/types'

describe('Batch exports', { concurrent: false }, () => {
    let context: Context
    const createdBatchExportIds: string[] = []

    const listTool = GENERATED_TOOLS['batch-exports-list']!()
    const getTool = GENERATED_TOOLS['batch-export-get']!()
    const createTool = GENERATED_TOOLS['batch-export-create']!()
    const updateTool = GENERATED_TOOLS['batch-export-update']!()
    const deleteTool = GENERATED_TOOLS['batch-export-delete']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        for (const id of createdBatchExportIds) {
            try {
                await deleteTool.handler(context, { id })
            } catch {
                // best effort — may already be deleted
            }
        }
        createdBatchExportIds.length = 0
    })

    // NoOp destination has no required config fields and no integration requirement, so it
    // is the easiest fixture for end-to-end lifecycle testing. Typed Databricks/AzureBlob
    // create paths require real Integration setup which isn't feasible in automated tests.
    function makeNoOpParams(overrides: Record<string, unknown> = {}): Record<string, unknown> {
        return {
            name: `test-batch-export-${generateUniqueKey('batch-export')}`,
            model: 'events',
            interval: 'hour',
            destination: {
                type: 'NoOp',
                config: {},
            },
            ...overrides,
        }
    }

    describe('batch-exports-list tool', () => {
        it('should return paginated structure', async () => {
            const result = await listTool.handler(context, {})
            const data = parseToolResponse(result)

            expect(typeof data.count).toBe('number')
            expect(Array.isArray(data.results)).toBe(true)
            expect(typeof data._posthogUrl).toBe('string')
            expect(data._posthogUrl).toContain('/data-pipelines/destinations')
        })

        it('should respect the limit parameter', async () => {
            const result = await listTool.handler(context, { limit: 1 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(1)
        })
    })

    describe('batch-export-create tool', () => {
        it('should create a NoOp batch export', async () => {
            const params = makeNoOpParams()
            const result = await createTool.handler(context, params)
            const batchExport = parseToolResponse(result)
            createdBatchExportIds.push(batchExport.id)

            expect(batchExport.id).toBeTruthy()
            expect(batchExport.name).toBe(params.name)
            expect(batchExport.interval).toBe('hour')
            expect(batchExport.destination.type).toBe('NoOp')
            expect(batchExport.paused).toBe(false)
        })
    })

    describe('batch-export-get tool', () => {
        it('should retrieve a specific batch export by ID', async () => {
            const created = await createTool.handler(context, makeNoOpParams())
            const createdBatchExport = parseToolResponse(created)
            createdBatchExportIds.push(createdBatchExport.id)

            const result = await getTool.handler(context, { id: createdBatchExport.id })
            const batchExport = parseToolResponse(result)

            expect(batchExport.id).toBe(createdBatchExport.id)
            expect(batchExport.name).toBe(createdBatchExport.name)
            expect(batchExport.destination.type).toBe('NoOp')
            expect(Array.isArray(batchExport.latest_runs)).toBe(true)
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(getTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('batch-export-update tool', () => {
        it('should update the name of a batch export', async () => {
            const created = await createTool.handler(context, makeNoOpParams())
            const batchExport = parseToolResponse(created)
            createdBatchExportIds.push(batchExport.id)

            const newName = `renamed-${generateUniqueKey('batch-export')}`
            const result = await updateTool.handler(context, { id: batchExport.id, name: newName })
            const updated = parseToolResponse(result)

            expect(updated.name).toBe(newName)
            expect(updated.id).toBe(batchExport.id)
        })

        it('should update interval', async () => {
            const created = await createTool.handler(context, makeNoOpParams({ interval: 'hour' }))
            const batchExport = parseToolResponse(created)
            createdBatchExportIds.push(batchExport.id)

            const result = await updateTool.handler(context, { id: batchExport.id, interval: 'day' })
            const updated = parseToolResponse(result)

            expect(updated.interval).toBe('day')
        })
    })

    describe('batch-export-delete tool', () => {
        it('should delete a batch export and subsequent get should fail', async () => {
            const created = await createTool.handler(context, makeNoOpParams())
            const batchExport = parseToolResponse(created)

            await deleteTool.handler(context, { id: batchExport.id })
            await expect(getTool.handler(context, { id: batchExport.id })).rejects.toThrow()
        })
    })

    describe('Batch exports workflow', () => {
        it('should support a full create → retrieve → update → delete lifecycle', async () => {
            const name = `workflow-${generateUniqueKey('batch-export')}`

            const createResult = await createTool.handler(context, makeNoOpParams({ name }))
            const created = parseToolResponse(createResult)
            expect(created.id).toBeTruthy()
            expect(created.name).toBe(name)

            const getResult = await getTool.handler(context, { id: created.id })
            const retrieved = parseToolResponse(getResult)
            expect(retrieved.id).toBe(created.id)

            const updatedName = `${name}-updated`
            const updateResult = await updateTool.handler(context, {
                id: created.id,
                name: updatedName,
                paused: true,
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.name).toBe(updatedName)
            expect(updated.paused).toBe(true)

            await deleteTool.handler(context, { id: created.id })
            await expect(getTool.handler(context, { id: created.id })).rejects.toThrow()
        })

        it('should appear in list results after creation', async () => {
            const name = `list-check-${generateUniqueKey('appear')}`

            const createResult = await createTool.handler(context, makeNoOpParams({ name }))
            const created = parseToolResponse(createResult)
            createdBatchExportIds.push(created.id)

            const listResult = await listTool.handler(context, {})
            const data = parseToolResponse(listResult)

            const found = data.results.find((b: any) => b.id === created.id)
            expect(found).toBeTruthy()
            expect(found.name).toBe(name)
        })
    })
})
