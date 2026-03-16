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
import { GENERATED_TOOLS } from '@/tools/generated/annotations'
import type { Context } from '@/tools/types'

describe('Annotations', { concurrent: false }, () => {
    let context: Context
    const createdAnnotationIds: number[] = []

    const createTool = GENERATED_TOOLS['annotation-create']!()
    const listTool = GENERATED_TOOLS['annotations-list']!()
    const retrieveTool = GENERATED_TOOLS['annotation-retrieve']!()
    const updateTool = GENERATED_TOOLS['annotations-partial-update']!()
    const deleteTool = GENERATED_TOOLS['annotation-delete']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        for (const id of createdAnnotationIds) {
            try {
                await deleteTool.handler(context, { id })
            } catch {
                // best effort — annotation may already be deleted
            }
        }
        createdAnnotationIds.length = 0
    })

    describe('annotation-create tool', () => {
        it('should create an annotation with all fields', async () => {
            const params = {
                content: `Test annotation ${generateUniqueKey('ann')}`,
                date_marker: '2024-01-15T12:00:00Z',
                scope: 'project' as const,
            }

            const result = await createTool.handler(context, params)
            const annotation = parseToolResponse(result)

            expect(annotation.id).toBeTruthy()
            expect(annotation.content).toBe(params.content)
            expect(annotation.date_marker).toContain('2024-01-15')
            expect(annotation.scope).toBe('project')

            createdAnnotationIds.push(annotation.id)
        })

        it('should create an annotation with minimal fields', async () => {
            const params = {
                content: `Minimal annotation ${generateUniqueKey('min')}`,
            }

            const result = await createTool.handler(context, params)
            const annotation = parseToolResponse(result)

            expect(annotation.id).toBeTruthy()
            expect(annotation.content).toBe(params.content)

            createdAnnotationIds.push(annotation.id)
        })
    })

    describe('annotations-list tool', () => {
        it('should list annotations including a newly created one', async () => {
            const createResult = await createTool.handler(context, {
                content: `List test annotation ${generateUniqueKey('list')}`,
                date_marker: '2024-02-01T00:00:00Z',
                scope: 'project' as const,
            })
            const created = parseToolResponse(createResult)
            createdAnnotationIds.push(created.id)

            const result = await listTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.some((a: { id: number }) => a.id === created.id)).toBe(true)
        })

        it('should support pagination', async () => {
            const result = await listTool.handler(context, { limit: 5, offset: 0 })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeLessThanOrEqual(5)
        })
    })

    describe('annotation-retrieve tool', () => {
        it('should retrieve an annotation by ID', async () => {
            const content = `Retrieve test ${generateUniqueKey('retrieve')}`
            const createResult = await createTool.handler(context, {
                content,
                date_marker: '2024-03-10T08:30:00Z',
                scope: 'project' as const,
            })
            const created = parseToolResponse(createResult)
            createdAnnotationIds.push(created.id)

            const result = await retrieveTool.handler(context, { id: created.id })
            const annotation = parseToolResponse(result)

            expect(annotation.id).toBe(created.id)
            expect(annotation.content).toBe(content)
            expect(annotation.date_marker).toContain('2024-03-10')
            expect(annotation.scope).toBe('project')
        })
    })

    describe('annotations-partial-update tool', () => {
        it('should update annotation content', async () => {
            const createResult = await createTool.handler(context, {
                content: `Original ${generateUniqueKey('orig')}`,
                date_marker: '2024-04-01T00:00:00Z',
                scope: 'project' as const,
            })
            const created = parseToolResponse(createResult)
            createdAnnotationIds.push(created.id)

            const updatedContent = `Updated ${generateUniqueKey('upd')}`
            const result = await updateTool.handler(context, {
                id: created.id,
                content: updatedContent,
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.content).toBe(updatedContent)
        })

        it('should update annotation date_marker', async () => {
            const createResult = await createTool.handler(context, {
                content: `Date update ${generateUniqueKey('date')}`,
                date_marker: '2024-05-01T00:00:00Z',
                scope: 'project' as const,
            })
            const created = parseToolResponse(createResult)
            createdAnnotationIds.push(created.id)

            const result = await updateTool.handler(context, {
                id: created.id,
                date_marker: '2024-06-15T12:00:00Z',
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.date_marker).toContain('2024-06-15')
        })

        it('should update annotation scope', async () => {
            const createResult = await createTool.handler(context, {
                content: `Scope update ${generateUniqueKey('scope')}`,
                date_marker: '2024-07-01T00:00:00Z',
                scope: 'project' as const,
            })
            const created = parseToolResponse(createResult)
            createdAnnotationIds.push(created.id)

            const result = await updateTool.handler(context, {
                id: created.id,
                scope: 'organization' as const,
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.scope).toBe('organization')
        })
    })

    describe('annotation-delete tool', () => {
        it('should delete an annotation', async () => {
            const createResult = await createTool.handler(context, {
                content: `Delete test ${generateUniqueKey('del')}`,
                date_marker: '2024-08-01T00:00:00Z',
                scope: 'project' as const,
            })
            const created = parseToolResponse(createResult)
            // Don't track for cleanup since we're deleting it here

            await deleteTool.handler(context, { id: created.id })

            const listResult = await listTool.handler(context, {})
            const response = parseToolResponse(listResult)
            expect(response.results.some((a: { id: number }) => a.id === created.id)).toBe(false)
        })
    })

    describe('full CRUD workflow', () => {
        it('should support create → retrieve → update → verify → delete', async () => {
            // Create
            const content = `CRUD workflow ${generateUniqueKey('crud')}`
            const createResult = await createTool.handler(context, {
                content,
                date_marker: '2024-09-01T00:00:00Z',
                scope: 'project' as const,
            })
            const created = parseToolResponse(createResult)
            expect(created.id).toBeTruthy()
            expect(created.content).toBe(content)

            // Retrieve
            const retrieveResult = await retrieveTool.handler(context, { id: created.id })
            const retrieved = parseToolResponse(retrieveResult)
            expect(retrieved.id).toBe(created.id)
            expect(retrieved.content).toBe(content)

            // Update
            const updatedContent = `Updated CRUD ${generateUniqueKey('crud-upd')}`
            const updateResult = await updateTool.handler(context, {
                id: created.id,
                content: updatedContent,
                date_marker: '2024-10-15T18:00:00Z',
                scope: 'organization' as const,
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.content).toBe(updatedContent)
            expect(updated.date_marker).toContain('2024-10-15')
            expect(updated.scope).toBe('organization')

            // Verify update via retrieve
            const verifyResult = await retrieveTool.handler(context, { id: created.id })
            const verified = parseToolResponse(verifyResult)
            expect(verified.content).toBe(updatedContent)
            expect(verified.scope).toBe('organization')

            // Delete
            await deleteTool.handler(context, { id: created.id })

            // Verify deletion
            const listResult = await listTool.handler(context, {})
            const response = parseToolResponse(listResult)
            expect(response.results.some((a: { id: number }) => a.id === created.id)).toBe(false)
        })
    })
})
