import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import createAnnotationTool from '@/tools/annotations/create'
import deleteAnnotationTool from '@/tools/annotations/delete'
import getAnnotationTool from '@/tools/annotations/get'
import getAllAnnotationsTool from '@/tools/annotations/getAll'
import updateAnnotationTool from '@/tools/annotations/update'
import type { Context } from '@/tools/types'

describe('Annotations', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
        annotations: []
    }

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources)
    })

    describe('create-annotation tool', () => {
        const createTool = createAnnotationTool()

        it('should create an annotation with required fields', async () => {
            const params = {
                data: {
                    content: generateUniqueKey('Test annotation'),
                    date_marker: new Date().toISOString(),
                    scope: 'project' as const,
                },
            }

            const result = await createTool.handler(context, params)
            const annotation = parseToolResponse(result)

            expect(annotation.id).toBeTruthy()
            expect(annotation.content).toBe(params.data.content)

            // Track for cleanup
            createdResources.featureFlags.push(annotation.id)
        })

        it('should create an annotation with all optional fields', async () => {
            const params = {
                data: {
                    content: generateUniqueKey('Full annotation'),
                    date_marker: new Date().toISOString(),
                    scope: 'dashboard' as const,
                    scope_id: '1',
                    insights: [],
                },
            }

            const result = await createTool.handler(context, params)
            const annotation = parseToolResponse(result)

            expect(annotation.id).toBeTruthy()
            expect(annotation.content).toBe(params.data.content)
            expect(annotation.scope).toBe(params.data.scope)

            createdResources.featureFlags.push(annotation.id)
        })
    })

    describe('update-annotation tool', () => {
        const createTool = createAnnotationTool()
        const updateTool = updateAnnotationTool()

        it('should update annotation content', async () => {
            const createParams = {
                data: {
                    content: generateUniqueKey('Original annotation'),
                    date_marker: new Date().toISOString(),
                    scope: 'project' as const,
                },
            }

            const createResult = await createTool.handler(context, createParams)
            const createdAnnotation = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdAnnotation.id)

            const updateParams = {
                annotationId: createdAnnotation.id,
                data: {
                    content: 'Updated annotation content',
                },
            }

            const updateResult = await updateTool.handler(context, updateParams)
            const updatedAnnotation = parseToolResponse(updateResult)

            expect(updatedAnnotation.id).toBe(createdAnnotation.id)
            expect(updatedAnnotation.content).toBe(updateParams.data.content)
        })
    })

    describe('get-annotation tool', () => {
        const createTool = createAnnotationTool()
        const getTool = getAnnotationTool()

        it('should retrieve a specific annotation by ID', async () => {
            const createParams = {
                data: {
                    content: generateUniqueKey('Get test annotation'),
                    date_marker: new Date().toISOString(),
                    scope: 'project' as const,
                },
            }

            const createResult = await createTool.handler(context, createParams)
            const createdAnnotation = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdAnnotation.id)

            const getParams = {
                annotationId: createdAnnotation.id,
            }

            const getResult = await getTool.handler(context, getParams)
            const retrievedAnnotation = parseToolResponse(getResult)

            expect(retrievedAnnotation.id).toBe(createdAnnotation.id)
            expect(retrievedAnnotation.content).toBe(createParams.data.content)
        })
    })

    describe('annotation-list tool', () => {
        const getAllTool = getAllAnnotationsTool()

        it('should return annotations with proper structure', async () => {
            const result = await getAllTool.handler(context, {})
            const annotations = parseToolResponse(result)

            expect(Array.isArray(annotations)).toBe(true)
            if (annotations.length > 0) {
                const annotation = annotations[0]
                expect(annotation).toHaveProperty('id')
                expect(annotation).toHaveProperty('content')
                expect(annotation).toHaveProperty('scope')
            }
        })

        it('should support filtering by scope', async () => {
            const createParams = {
                data: {
                    content: generateUniqueKey('Scoped annotation'),
                    date_marker: new Date().toISOString(),
                    scope: 'dashboard' as const,
                    scope_id: '1',
                },
            }

            const createTool = createAnnotationTool()
            const createResult = await createTool.handler(context, createParams)
            const createdAnnotation = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdAnnotation.id)

            const listParams = {
                data: {
                    scope: 'dashboard' as const,
                },
            }

            const listResult = await getAllTool.handler(context, listParams)
            const annotations = parseToolResponse(listResult)

            expect(Array.isArray(annotations)).toBe(true)
            // The created annotation should be in the filtered results
            const foundAnnotation = annotations.find((a: typeof annotations[0]) => a.id === createdAnnotation.id)
            expect(foundAnnotation).toBeTruthy()
        })
    })

    describe('delete-annotation tool', () => {
        const createTool = createAnnotationTool()
        const deleteTool = deleteAnnotationTool()

        it('should delete an annotation', async () => {
            const createParams = {
                data: {
                    content: generateUniqueKey('Delete test annotation'),
                    date_marker: new Date().toISOString(),
                    scope: 'project' as const,
                },
            }

            const createResult = await createTool.handler(context, createParams)
            const createdAnnotation = parseToolResponse(createResult)

            const deleteParams = {
                annotationId: createdAnnotation.id,
            }

            const deleteResult = await deleteTool.handler(context, deleteParams)
            const deleteResponse = parseToolResponse(deleteResult)

            expect(deleteResponse.success).toBe(true)
        })
    })

    describe('Annotation workflow', () => {
        it('should support full CRUD workflow', async () => {
            const createTool = createAnnotationTool()
            const updateTool = updateAnnotationTool()
            const getTool = getAnnotationTool()
            const deleteTool = deleteAnnotationTool()

            // Create
            const createParams = {
                data: {
                    content: generateUniqueKey('Workflow test annotation'),
                    date_marker: new Date().toISOString(),
                    scope: 'project' as const,
                },
            }

            const createResult = await createTool.handler(context, createParams)
            const createdAnnotation = parseToolResponse(createResult)

            expect(createdAnnotation.id).toBeTruthy()
            createdResources.featureFlags.push(createdAnnotation.id)

            // Read
            const getResult = await getTool.handler(context, { annotationId: createdAnnotation.id })
            const retrievedAnnotation = parseToolResponse(getResult)

            expect(retrievedAnnotation.id).toBe(createdAnnotation.id)

            // Update
            const updateParams = {
                annotationId: createdAnnotation.id,
                data: {
                    content: 'Updated workflow annotation',
                },
            }

            const updateResult = await updateTool.handler(context, updateParams)
            const updatedAnnotation = parseToolResponse(updateResult)

            expect(updatedAnnotation.content).toBe(updateParams.data.content)

            // Delete
            const deleteResult = await deleteTool.handler(context, {
                annotationId: updatedAnnotation.id,
            })
            const deleteResponse = parseToolResponse(deleteResult)

            expect(deleteResponse.success).toBe(true)
        })
    })
})
