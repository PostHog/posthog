import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import {
    validateEnvironmentVariables,
    createTestClient,
    createTestContext,
    setActiveProjectAndOrg,
    cleanupResources,
    TEST_PROJECT_ID,
    TEST_ORG_ID,
    type CreatedResources,
    parseToolResponse,
    generateUniqueKey,
} from '@/shared/test-utils'
import createFeatureFlagTool from '@/tools/featureFlags/create'
import updateFeatureFlagTool from '@/tools/featureFlags/update'
import deleteFeatureFlagTool from '@/tools/featureFlags/delete'
import getAllFeatureFlagsTool from '@/tools/featureFlags/getAll'
import getFeatureFlagDefinitionTool from '@/tools/featureFlags/getDefinition'
import type { Context } from '@/tools/types'

describe('Feature Flags', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
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
        const createTool = createFeatureFlagTool()

        it('should create a feature flag with minimal required fields', async () => {
            const params = {
                name: 'Test Feature Flag',
                key: generateUniqueKey('test-flag'),
                description: 'Integration test flag',
                filters: { groups: [] },
                active: true,
            }

            const result = await createTool.handler(context, params)

            const flagData = parseToolResponse(result)
            expect(flagData.id).toBeDefined()
            expect(flagData.key).toBe(params.key)
            expect(flagData.name).toBe(params.name)
            expect(flagData.active).toBe(params.active)
            expect(flagData.url).toContain('/feature_flags/')

            createdResources.featureFlags.push(flagData.id)
        })

        it('should create a feature flag with tags', async () => {
            const params = {
                name: 'Tagged Feature Flag',
                key: generateUniqueKey('tagged-flag'),
                description: 'Flag with tags',
                filters: { groups: [] },
                active: true,
                tags: ['test', 'integration'],
            }

            const result = await createTool.handler(context, params)
            const flagData = parseToolResponse(result)

            expect(flagData.id).toBeDefined()
            expect(flagData.key).toBe(params.key)
            expect(flagData.name).toBe(params.name)

            createdResources.featureFlags.push(flagData.id)
        })

        it('should create a feature flag with complex filters', async () => {
            const params = {
                name: 'Complex Filter Flag',
                key: generateUniqueKey('complex-flag'),
                description: 'Flag with complex filters',
                active: true,
                filters: {
                    groups: [
                        {
                            variant: null,
                            properties: [
                                {
                                    key: 'email',
                                    type: 'person',
                                    value: 'test@example.com',
                                    operator: 'exact',
                                },
                            ],
                            rollout_percentage: 100,
                        },
                    ],
                },
            }

            const result = await createTool.handler(context, params)
            const flagData = parseToolResponse(result)

            expect(flagData.id).toBeDefined()
            expect(flagData.key).toBe(params.key)
            expect(flagData.name).toBe(params.name)

            createdResources.featureFlags.push(flagData.id)
        })
    })

    describe('update-feature-flag tool', () => {
        const createTool = createFeatureFlagTool()
        const updateTool = updateFeatureFlagTool()

        it('should update a feature flag by key', async () => {
            // First create a flag
            const createParams = {
                name: 'Original Name',
                key: generateUniqueKey('update-test'),
                description: 'Original description',
                filters: { groups: [] },
                active: true,
            }

            const createResult = await createTool.handler(context, createParams)
            const createdFlag = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdFlag.id)

            // Update the flag
            const updateParams = {
                flagKey: createParams.key,
                data: {
                    name: 'Updated Name',
                    description: 'Updated description',
                    active: false,
                },
            }

            const updateResult = await updateTool.handler(context, updateParams)
            const updatedFlag = parseToolResponse(updateResult)

            expect(updatedFlag.name).toBe('Updated Name')
            expect(updatedFlag.active).toBe(false)
            expect(updatedFlag.key).toBe(createParams.key)
        })

        it('should update feature flag filters', async () => {
            // Create a flag
            const createParams = {
                name: 'Filter Update Test',
                key: generateUniqueKey('filter-update'),
                description: 'Testing filter updates',
                filters: { groups: [] },
                active: true,
            }

            const createResult = await createTool.handler(context, createParams)
            const createdFlag = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdFlag.id)

            // Update with new filters
            const updateParams = {
                flagKey: createParams.key,
                data: {
                    filters: {
                        groups: [
                            {
                                variant: null,
                                properties: [],
                                rollout_percentage: 50,
                            },
                        ],
                    },
                },
            }

            const updateResult = await updateTool.handler(context, updateParams)
            const updatedFlag = parseToolResponse(updateResult)

            expect(updatedFlag.id).toBeDefined()
            expect(updatedFlag.key).toBe(createParams.key)
        })
    })

    describe('get-all-feature-flags tool', () => {
        const createTool = createFeatureFlagTool()
        const getAllTool = getAllFeatureFlagsTool()

        it('should list all feature flags', async () => {
            // Create a few test flags
            const testFlags = []
            for (let i = 0; i < 3; i++) {
                const params = {
                    name: `List Test Flag ${i}`,
                    key: generateUniqueKey(`list-test-${i}`),
                    description: `Test flag ${i}`,
                    filters: { groups: [] },
                    active: true,
                }

                const result = await createTool.handler(context, params)
                const flag = parseToolResponse(result)
                testFlags.push(flag)
                createdResources.featureFlags.push(flag.id)
            }

            // Get all flags
            const result = await getAllTool.handler(context, {})
            const allFlags = parseToolResponse(result)

            expect(Array.isArray(allFlags)).toBe(true)
            expect(allFlags.length).toBeGreaterThanOrEqual(3)

            // Verify our test flags are in the list
            for (const testFlag of testFlags) {
                const found = allFlags.find((f: any) => f.id === testFlag.id)
                expect(found).toBeDefined()
                expect(found.key).toBe(testFlag.key)
            }
        })

        it('should return flags with proper structure', async () => {
            const result = await getAllTool.handler(context, {})
            const flags = parseToolResponse(result)

            if (flags.length > 0) {
                const flag = flags[0]
                expect(flag).toHaveProperty('id')
                expect(flag).toHaveProperty('key')
                expect(flag).toHaveProperty('name')
                expect(flag).toHaveProperty('active')
            }
        })
    })

    describe('get-feature-flag-definition tool', () => {
        const createTool = createFeatureFlagTool()
        const getDefinitionTool = getFeatureFlagDefinitionTool()

        it('should get feature flag definition by key', async () => {
            // Create a flag
            const createParams = {
                name: 'Definition Test Flag',
                key: generateUniqueKey('definition-test'),
                description: 'Test flag for definition',
                filters: { groups: [] },
                active: true,
                tags: ['test-tag'],
            }

            const createResult = await createTool.handler(context, createParams)
            const createdFlag = parseToolResponse(createResult)
            createdResources.featureFlags.push(createdFlag.id)

            // Get definition
            const result = await getDefinitionTool.handler(context, { flagKey: createParams.key })
            const definition = parseToolResponse(result)

            expect(definition.id).toBe(createdFlag.id)
            expect(definition.key).toBe(createParams.key)
            expect(definition.name).toBe(createParams.name)
            expect(definition.active).toBe(createParams.active)
        })

        it('should return error message for non-existent flag key', async () => {
            const nonExistentKey = generateUniqueKey('non-existent')

            const result = await getDefinitionTool.handler(context, { flagKey: nonExistentKey })

            expect(result.content[0].text).toBe(
                `Error: Flag with key "${nonExistentKey}" not found.`
            )
        })
    })

    describe('delete-feature-flag tool', () => {
        const createTool = createFeatureFlagTool()
        const deleteTool = deleteFeatureFlagTool()

        it('should delete a feature flag by key', async () => {
            // Create a flag
            const createParams = {
                name: 'Delete Test Flag',
                key: generateUniqueKey('delete-test'),
                description: 'Test flag for deletion',
                filters: { groups: [] },
                active: true,
            }

            await createTool.handler(context, createParams)

            // Delete the flag
            const deleteResult = await deleteTool.handler(context, { flagKey: createParams.key })

            expect(deleteResult.content).toBeDefined()
            expect(deleteResult.content[0].type).toBe('text')
            const deleteResponse = parseToolResponse(deleteResult)
            expect(deleteResponse.success).toBe(true)
            expect(deleteResponse.message).toContain('deleted successfully')

            // Verify it's deleted by trying to get it
            const getDefinitionTool = getFeatureFlagDefinitionTool()
            const getResult = await getDefinitionTool.handler(context, {
                flagKey: createParams.key,
            })
            expect(getResult.content[0].text).toBe(
                `Error: Flag with key "${createParams.key}" not found.`
            )
        })

        it('should handle deletion of non-existent flag', async () => {
            const nonExistentKey = generateUniqueKey('non-existent-delete')

            const result = await deleteTool.handler(context, { flagKey: nonExistentKey })
            expect(result.content[0].text).toBe('Feature flag is already deleted.')
        })
    })

    describe('Feature flag workflow', () => {
        it('should support full CRUD workflow', async () => {
            const createTool = createFeatureFlagTool()
            const updateTool = updateFeatureFlagTool()
            const getDefinitionTool = getFeatureFlagDefinitionTool()
            const deleteTool = deleteFeatureFlagTool()

            const flagKey = generateUniqueKey('workflow-test')

            // Create
            const createParams = {
                name: 'Workflow Test Flag',
                key: flagKey,
                description: 'Testing full workflow',
                filters: { groups: [] },
                active: false,
            }

            const createResult = await createTool.handler(context, createParams)
            const createdFlag = parseToolResponse(createResult)

            // Read
            const getResult = await getDefinitionTool.handler(context, { flagKey: flagKey })
            const retrievedFlag = parseToolResponse(getResult)
            expect(retrievedFlag.id).toBe(createdFlag.id)

            // Update
            const updateParams = {
                flagKey: flagKey,
                data: {
                    active: true,
                    name: 'Updated Workflow Flag',
                },
            }

            const updateResult = await updateTool.handler(context, updateParams)
            const updatedFlag = parseToolResponse(updateResult)
            expect(updatedFlag.active).toBe(true)
            expect(updatedFlag.name).toBe('Updated Workflow Flag')

            // Delete
            const deleteResult = await deleteTool.handler(context, { flagKey: flagKey })
            const deleteResponse = parseToolResponse(deleteResult)
            expect(deleteResponse.success).toBe(true)
            expect(deleteResponse.message).toContain('deleted successfully')
        })
    })
})
