import crypto from 'crypto'
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
import { GENERATED_TOOLS } from '@/tools/generated/early_access_features'
import type { Context } from '@/tools/types'

describe('Early access features', { concurrent: false }, () => {
    let context: Context
    const createdFeatureIds: string[] = []

    const listTool = GENERATED_TOOLS['early-access-feature-list']!()
    const createTool = GENERATED_TOOLS['early-access-feature-create']!()
    const retrieveTool = GENERATED_TOOLS['early-access-feature-retrieve']!()
    const updateTool = GENERATED_TOOLS['early-access-feature-partial-update']!()
    const deleteTool = GENERATED_TOOLS['early-access-feature-destroy']!()

    const makeFeatureParams = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
        name: `Test feature ${generateUniqueKey('eaf')}`,
        description: 'A test early access feature',
        stage: 'beta' as const,
        ...overrides,
    })

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        for (const id of createdFeatureIds) {
            try {
                await deleteTool.handler(context, { id })
            } catch {
                // best effort — feature may already be deleted
            }
        }
        createdFeatureIds.length = 0
    })

    describe('early-access-feature-create tool', () => {
        it('should create a feature with all fields', async () => {
            const params = makeFeatureParams({
                documentation_url: 'https://example.com/docs',
            })

            const result = await createTool.handler(context, params)
            const feature = parseToolResponse(result)

            expect(feature.id).toBeTruthy()
            expect(feature.name).toBe(params.name)
            expect(feature.description).toBe(params.description)
            expect(feature.stage).toBe('beta')
            expect(feature.documentation_url).toBe('https://example.com/docs')
            expect(feature.feature_flag).toBeTruthy()

            createdFeatureIds.push(feature.id)
        })

        it('should create a feature with minimal fields', async () => {
            const params = {
                name: `Minimal feature ${generateUniqueKey('min')}`,
                stage: 'draft' as const,
            }

            const result = await createTool.handler(context, params)
            const feature = parseToolResponse(result)

            expect(feature.id).toBeTruthy()
            expect(feature.name).toBe(params.name)
            expect(feature.stage).toBe('draft')

            createdFeatureIds.push(feature.id)
        })
    })

    describe('early-access-feature-list tool', () => {
        it('should list features including a newly created one', async () => {
            const createResult = await createTool.handler(context, makeFeatureParams())
            const created = parseToolResponse(createResult)
            createdFeatureIds.push(created.id)

            const result = await listTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.some((f: { id: string }) => f.id === created.id)).toBe(true)
        })

        it('should support pagination', async () => {
            const result = await listTool.handler(context, { limit: 5, offset: 0 })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeLessThanOrEqual(5)
        })
    })

    describe('early-access-feature-retrieve tool', () => {
        it('should retrieve a feature by ID', async () => {
            const params = makeFeatureParams()
            const createResult = await createTool.handler(context, params)
            const created = parseToolResponse(createResult)
            createdFeatureIds.push(created.id)

            const result = await retrieveTool.handler(context, { id: created.id })
            const feature = parseToolResponse(result)

            expect(feature.id).toBe(created.id)
            expect(feature.name).toBe(params.name)
            expect(feature.stage).toBe('beta')
        })

        it('should throw for a non-existent ID', async () => {
            await expect(retrieveTool.handler(context, { id: crypto.randomUUID() })).rejects.toThrow()
        })
    })

    describe('early-access-feature-partial-update tool', () => {
        it('should update the name', async () => {
            const createResult = await createTool.handler(context, makeFeatureParams())
            const created = parseToolResponse(createResult)
            createdFeatureIds.push(created.id)

            const updatedName = `Updated ${generateUniqueKey('upd')}`
            const result = await updateTool.handler(context, {
                id: created.id,
                name: updatedName,
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.name).toBe(updatedName)
        })

        it('should update the stage', async () => {
            const createResult = await createTool.handler(context, makeFeatureParams({ stage: 'draft' as const }))
            const created = parseToolResponse(createResult)
            createdFeatureIds.push(created.id)

            const result = await updateTool.handler(context, {
                id: created.id,
                stage: 'alpha' as const,
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.stage).toBe('alpha')
        })

        it('should update the description', async () => {
            const createResult = await createTool.handler(context, makeFeatureParams())
            const created = parseToolResponse(createResult)
            createdFeatureIds.push(created.id)

            const result = await updateTool.handler(context, {
                id: created.id,
                description: 'Updated description',
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.description).toBe('Updated description')
        })
    })

    describe('early-access-feature-destroy tool', () => {
        it('should delete a feature', async () => {
            const createResult = await createTool.handler(context, makeFeatureParams())
            const created = parseToolResponse(createResult)

            await deleteTool.handler(context, { id: created.id })

            const listResult = await listTool.handler(context, {})
            const response = parseToolResponse(listResult)
            expect(response.results.some((f: { id: string }) => f.id === created.id)).toBe(false)
        })
    })

    describe('full CRUD workflow', () => {
        it('should support create → retrieve → update → verify → delete', async () => {
            // Create
            const params = makeFeatureParams({ stage: 'draft' as const })
            const createResult = await createTool.handler(context, params)
            const created = parseToolResponse(createResult)
            expect(created.id).toBeTruthy()
            expect(created.name).toBe(params.name)
            expect(created.stage).toBe('draft')

            // Retrieve
            const retrieveResult = await retrieveTool.handler(context, { id: created.id })
            const retrieved = parseToolResponse(retrieveResult)
            expect(retrieved.id).toBe(created.id)
            expect(retrieved.name).toBe(params.name)

            // Update
            const updatedName = `Updated CRUD ${generateUniqueKey('crud-upd')}`
            const updateResult = await updateTool.handler(context, {
                id: created.id,
                name: updatedName,
                stage: 'beta' as const,
                description: 'Updated via CRUD test',
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.name).toBe(updatedName)
            expect(updated.stage).toBe('beta')
            expect(updated.description).toBe('Updated via CRUD test')

            // Verify update via retrieve
            const verifyResult = await retrieveTool.handler(context, { id: created.id })
            const verified = parseToolResponse(verifyResult)
            expect(verified.name).toBe(updatedName)
            expect(verified.stage).toBe('beta')

            // Delete
            await deleteTool.handler(context, { id: created.id })

            // Verify deletion
            const listResult = await listTool.handler(context, {})
            const response = parseToolResponse(listResult)
            expect(response.results.some((f: { id: string }) => f.id === created.id)).toBe(false)
        })
    })
})
