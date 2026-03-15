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
import { GENERATED_TOOLS } from '@/tools/generated/feature_flags'
import type { Context } from '@/tools/types'

describe('Feature flags', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
        cohorts: [],
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

    describe('create-feature-flag tool', () => {
        const createTool = GENERATED_TOOLS['create-feature-flag']!()

        it('should create a feature flag with minimal required fields', async () => {
            const params = {
                name: 'Test feature flag',
                key: generateUniqueKey('test-flag'),
                filters: {
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: 100,
                        },
                    ],
                },
                active: true,
            }

            const result = await createTool.handler(context, params)
            const flagData = parseToolResponse(result)

            expect(flagData.id).toBeTruthy()
            expect(flagData.key).toBe(params.key)
            expect(flagData.name).toBe(params.name)
            expect(flagData.active).toBe(params.active)
            expect(flagData._posthogUrl).toContain('/feature_flags/')
            expect(flagData.updated_at).toBeTruthy()

            createdResources.featureFlags.push(flagData.id)
        })

        it('should create a feature flag with tags and evaluation tags', async () => {
            const params = {
                name: 'Tagged feature flag',
                key: generateUniqueKey('tagged-flag'),
                filters: {
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: 100,
                        },
                    ],
                },
                active: true,
                tags: ['test', 'integration'],
                evaluation_tags: ['test'],
            }

            const result = await createTool.handler(context, params)
            const flagData = parseToolResponse(result)

            expect(flagData.id).toBeTruthy()
            expect(flagData.key).toBe(params.key)
            expect(flagData.name).toBe(params.name)

            createdResources.featureFlags.push(flagData.id)
        })

        it('should create a multivariate feature flag', async () => {
            const params = {
                name: 'Multivariate flag',
                key: generateUniqueKey('multi-flag'),
                active: true,
                filters: {
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: 100,
                        },
                    ],
                    multivariate: {
                        variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                },
            }

            const result = await createTool.handler(context, params)
            const flagData = parseToolResponse(result)

            expect(flagData.id).toBeTruthy()
            expect(flagData.filters.multivariate.variants).toHaveLength(2)

            createdResources.featureFlags.push(flagData.id)
        })
    })

    describe('feature-flag-get-all tool', () => {
        const getAllTool = GENERATED_TOOLS['feature-flag-get-all']!()
        const createTool = GENERATED_TOOLS['create-feature-flag']!()
        const getTool = GENERATED_TOOLS['feature-flag-get-definition']!()

        it('should list feature flags', async () => {
            const createResult = await createTool.handler(context, {
                name: 'List test flag',
                key: generateUniqueKey('list-test'),
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100 }],
                },
                active: true,
            })
            const createdFlag = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdFlag.id)

            const result = await getAllTool.handler(context, { limit: 10, offset: 0 })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.some((flag: { id: number }) => flag.id === createdFlag.id)).toBe(true)
            expect(response._posthogUrl).toContain('/feature_flags')
        })

        it('should support search by key and use returned ID for retrieval', async () => {
            const uniqueKey = generateUniqueKey('search-key')
            const createResult = await createTool.handler(context, {
                name: 'Search test flag',
                key: uniqueKey,
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100 }],
                },
                active: true,
            })
            const createdFlag = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdFlag.id)

            const searchResult = await getAllTool.handler(context, { search: uniqueKey, limit: 20, offset: 0 })
            const listResponse = parseToolResponse(searchResult)
            const found = listResponse.results.find((flag: { id: number; key: string }) => flag.key === uniqueKey)

            expect(found).toBeTruthy()
            if (!found) {
                throw new Error(`Expected to find feature flag with key ${uniqueKey}`)
            }
            expect(found.id).toBe(createdFlag.id)

            const getResult = await getTool.handler(context, { id: found.id })
            const flagData = parseToolResponse(getResult)
            expect(flagData.id).toBe(createdFlag.id)
            expect(flagData.key).toBe(uniqueKey)
        })
    })

    describe('feature-flag-get-definition tool', () => {
        const getTool = GENERATED_TOOLS['feature-flag-get-definition']!()
        const createTool = GENERATED_TOOLS['create-feature-flag']!()

        it('should get a feature flag by ID', async () => {
            const createResult = await createTool.handler(context, {
                name: 'Definition test flag',
                key: generateUniqueKey('definition-test'),
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100 }],
                },
                active: true,
            })
            const createdFlag = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdFlag.id)

            const result = await getTool.handler(context, { id: createdFlag.id })
            const flagData = parseToolResponse(result)

            expect(flagData.id).toBe(createdFlag.id)
            expect(flagData.key).toBe(createdFlag.key)
            expect(flagData._posthogUrl).toContain('/feature_flags/')
        })
    })

    describe('update-feature-flag tool', () => {
        const updateTool = GENERATED_TOOLS['update-feature-flag']!()
        const createTool = GENERATED_TOOLS['create-feature-flag']!()

        it('should update a feature flag by ID', async () => {
            const createResult = await createTool.handler(context, {
                name: 'Original name',
                key: generateUniqueKey('update-test'),
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100 }],
                },
                active: true,
            })
            const createdFlag = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdFlag.id)

            const updateResult = await updateTool.handler(context, {
                id: createdFlag.id,
                name: 'Updated name',
                active: false,
            })
            const updatedFlag = parseToolResponse(updateResult)

            expect(updatedFlag.id).toBe(createdFlag.id)
            expect(updatedFlag.name).toBe('Updated name')
            expect(updatedFlag.active).toBe(false)
            expect(updatedFlag._posthogUrl).toContain('/feature_flags/')
        })

        it('should update feature flag filters', async () => {
            const createResult = await createTool.handler(context, {
                name: 'Filter update flag',
                key: generateUniqueKey('filter-update'),
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100 }],
                },
                active: true,
            })
            const createdFlag = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdFlag.id)

            const updateResult = await updateTool.handler(context, {
                id: createdFlag.id,
                filters: {
                    groups: [{ properties: [], rollout_percentage: 50 }],
                },
            })
            const updatedFlag = parseToolResponse(updateResult)

            expect(updatedFlag.id).toBe(createdFlag.id)
        })
    })

    describe('delete-feature-flag tool', () => {
        const deleteTool = GENERATED_TOOLS['delete-feature-flag']!()
        const getAllTool = GENERATED_TOOLS['feature-flag-get-all']!()
        const createTool = GENERATED_TOOLS['create-feature-flag']!()

        it('should delete a feature flag by ID', async () => {
            const createResult = await createTool.handler(context, {
                name: 'Delete test flag',
                key: generateUniqueKey('delete-test'),
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100 }],
                },
                active: true,
            })
            const createdFlag = parseToolResponse(createResult)

            await deleteTool.handler(context, { id: createdFlag.id })

            const listResult = await getAllTool.handler(context, { limit: 100, offset: 0 })
            const listResponse = parseToolResponse(listResult)
            expect(listResponse.results.some((flag: { id: number }) => flag.id === createdFlag.id)).toBe(false)
        })
    })

    describe('Feature flag workflow', () => {
        it('should support full CRUD workflow', async () => {
            const createTool = GENERATED_TOOLS['create-feature-flag']!()
            const updateTool = GENERATED_TOOLS['update-feature-flag']!()
            const getTool = GENERATED_TOOLS['feature-flag-get-definition']!()
            const deleteTool = GENERATED_TOOLS['delete-feature-flag']!()

            const createResult = await createTool.handler(context, {
                name: 'Workflow test flag',
                key: generateUniqueKey('workflow-test'),
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100 }],
                },
                active: false,
            })
            const createdFlag = parseToolResponse(createResult)

            const getResult = await getTool.handler(context, { id: createdFlag.id })
            const retrievedFlag = parseToolResponse(getResult)
            expect(retrievedFlag.id).toBe(createdFlag.id)

            const updateResult = await updateTool.handler(context, {
                id: createdFlag.id,
                active: true,
                name: 'Updated workflow flag',
            })
            const updatedFlag = parseToolResponse(updateResult)
            expect(updatedFlag.active).toBe(true)
            expect(updatedFlag.name).toBe('Updated workflow flag')

            await deleteTool.handler(context, { id: createdFlag.id })
        })
    })
})
