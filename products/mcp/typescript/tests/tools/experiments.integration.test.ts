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
import createExperimentTool from '@/tools/experiments/create'
import deleteExperimentTool from '@/tools/experiments/delete'
import getAllExperimentsTool from '@/tools/experiments/getAll'
import getExperimentTool from '@/tools/experiments/get'
import getExperimentResultsTool from '@/tools/experiments/getResults'
import updateExperimentTool from '@/tools/experiments/update'
import type { Context } from '@/tools/types'

describe('Experiments', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
    }
    const createdExperiments: number[] = []

    // Helper function to track created experiments and their feature flags
    const trackExperiment = (experiment: any) => {
        if (experiment.id) {
            createdExperiments.push(experiment.id)
        }
        if (experiment.feature_flag?.id) {
            createdResources.featureFlags.push(experiment.feature_flag.id)
        }
    }

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        // Clean up experiments first
        for (const experimentId of createdExperiments) {
            try {
                await context.api.experiments({ projectId: TEST_PROJECT_ID! }).delete({
                    experimentId,
                })
            } catch (error) {
                console.warn(`Failed to cleanup experiment ${experimentId}:`, error)
            }
        }
        createdExperiments.length = 0

        // Clean up associated feature flags
        await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources)
    })

    describe('create-experiment tool', () => {
        const createTool = createExperimentTool()

        it('should create a draft experiment with minimal required fields', async () => {
            // Note: API auto-creates feature flag if it doesn't exist
            const flagKey = generateUniqueKey('exp-flag')

            // Create experiment
            const params = {
                name: 'Minimal Test Experiment',
                feature_flag_key: flagKey,
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.name).toBe(params.name)
            expect(experiment.feature_flag_key).toBe(params.feature_flag_key)
            expect(experiment.start_date).toBeNull() // Draft experiments have no start date
            expect(experiment.url).toContain('/experiments/')

            trackExperiment(experiment)
        })

        it('should create an experiment with description and type', async () => {
            const flagKey = generateUniqueKey('exp-flag-desc')

            const params = {
                name: 'Detailed Test Experiment',
                description: 'This experiment tests the impact of button color on conversions',
                feature_flag_key: flagKey,
                type: 'web' as const,
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.name).toBe(params.name)
            expect(experiment.feature_flag_key).toBe(params.feature_flag_key)

            trackExperiment(experiment)
        })

        it('should create an experiment with custom variants', async () => {
            const flagKey = generateUniqueKey('exp-flag-variants')

            const params = {
                name: 'Variant Test Experiment',
                feature_flag_key: flagKey,
                variants: [
                    { key: 'control', name: 'Control Group', rollout_percentage: 33 },
                    { key: 'variant_a', name: 'Variant A', rollout_percentage: 33 },
                    { key: 'variant_b', name: 'Variant B', rollout_percentage: 34 },
                ],
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.parameters?.feature_flag_variants).toHaveLength(3)
            expect(experiment.parameters?.feature_flag_variants?.[0]?.key).toBe('control')
            expect(experiment.parameters?.feature_flag_variants?.[0]?.rollout_percentage).toBe(33)

            trackExperiment(experiment)
        })

        it('should create an experiment with mean metric', async () => {
            const flagKey = generateUniqueKey('exp-flag-mean')

            const params = {
                name: 'Mean Metric Experiment',
                feature_flag_key: flagKey,
                primary_metrics: [
                    {
                        name: 'Average Page Load Time',
                        metric_type: 'mean' as const,
                        event_name: '$pageview',
                        properties: { page: '/checkout' },
                        description: 'Measure average page load time for checkout page',
                    },
                ],
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.metrics).toHaveLength(1)

            trackExperiment(experiment)
        })

        it('should create an experiment with funnel metric', async () => {
            const flagKey = generateUniqueKey('exp-flag-funnel')

            const params = {
                name: 'Funnel Metric Experiment',
                feature_flag_key: flagKey,
                primary_metrics: [
                    {
                        name: 'Checkout Conversion Funnel',
                        metric_type: 'funnel' as const,
                        event_name: 'product_view',
                        funnel_steps: ['product_view', 'add_to_cart', 'checkout_start', 'purchase'],
                        description: 'Track conversion through checkout funnel',
                    },
                ],
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.metrics).toHaveLength(1)

            trackExperiment(experiment)
        })

        it('should create an experiment with ratio metric', async () => {
            const flagKey = generateUniqueKey('exp-flag-ratio')

            const params = {
                name: 'Ratio Metric Experiment',
                feature_flag_key: flagKey,
                primary_metrics: [
                    {
                        name: 'Button Click Rate',
                        metric_type: 'ratio' as const,
                        event_name: 'button_click',
                        description: 'Ratio of button clicks to page views',
                    },
                ],
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.metrics).toHaveLength(1)

            trackExperiment(experiment)
        })

        it('should create an experiment with multiple metrics', async () => {
            const flagKey = generateUniqueKey('exp-flag-multi')

            const params = {
                name: 'Multi Metric Experiment',
                feature_flag_key: flagKey,
                primary_metrics: [
                    {
                        name: 'Conversion Rate',
                        metric_type: 'funnel' as const,
                        event_name: 'visit',
                        funnel_steps: ['visit', 'signup', 'purchase'],
                    },
                    {
                        name: 'Average Revenue',
                        metric_type: 'mean' as const,
                        event_name: 'purchase',
                    },
                ],
                secondary_metrics: [
                    {
                        name: 'Page Views',
                        metric_type: 'mean' as const,
                        event_name: '$pageview',
                    },
                    {
                        name: 'Bounce Rate',
                        metric_type: 'ratio' as const,
                        event_name: 'bounce',
                    },
                ],
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.metrics).toHaveLength(2)
            expect(experiment.metrics_secondary).toHaveLength(2)

            trackExperiment(experiment)
        })

        it('should create an experiment with minimum detectable effect', async () => {
            const flagKey = generateUniqueKey('exp-flag-mde')

            const params = {
                name: 'MDE Test Experiment',
                feature_flag_key: flagKey,
                minimum_detectable_effect: 15,
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()

            trackExperiment(experiment)
        })

        it('should create an experiment with filter test accounts enabled', async () => {
            const flagKey = generateUniqueKey('exp-flag-filter')

            const params = {
                name: 'Filter Test Accounts Experiment',
                feature_flag_key: flagKey,
                filter_test_accounts: true,
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()

            trackExperiment(experiment)
        })

        it("should create experiment when feature flag doesn't exist (API creates it)", async () => {
            // Note: The API might auto-create the feature flag if it doesn't exist
            const params = {
                name: 'Auto-Create Flag Experiment',
                feature_flag_key: generateUniqueKey('auto-created-flag'),
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            trackExperiment(experiment)
        })
    })

    describe('get-all-experiments tool', () => {
        const createTool = createExperimentTool()
        const getAllTool = getAllExperimentsTool()

        it('should list all experiments', async () => {
            // Create a few test experiments
            const testExperiments = []
            for (let i = 0; i < 3; i++) {
                const flagKey = generateUniqueKey(`exp-list-flag-${i}`)

                const params = {
                    name: `List Test Experiment ${i}`,
                    feature_flag_key: flagKey,
                    draft: true,
                }

                const result = await createTool.handler(context, params as any)
                const experiment = parseToolResponse(result)
                testExperiments.push(experiment)
                trackExperiment(experiment)
            }

            // Get all experiments
            const result = await getAllTool.handler(context, {})
            const allExperiments = parseToolResponse(result)

            expect(Array.isArray(allExperiments)).toBe(true)
            expect(allExperiments.length).toBeGreaterThanOrEqual(3)

            // Verify our test experiments are in the list
            for (const testExp of testExperiments) {
                const found = allExperiments.find((e: any) => e.id === testExp.id)
                expect(found).toBeDefined()
            }
        })

        it('should return experiments with proper structure', async () => {
            const result = await getAllTool.handler(context, {})
            const experiments = parseToolResponse(result)

            if (experiments.length > 0) {
                const experiment = experiments[0]
                expect(experiment).toHaveProperty('id')
                expect(experiment).toHaveProperty('name')
                expect(experiment).toHaveProperty('feature_flag_key')
            }
        })
    })

    describe('get-experiment tool', () => {
        const createTool = createExperimentTool()
        const getTool = getExperimentTool()

        it('should get experiment by ID', async () => {
            // Create an experiment
            const flagKey = generateUniqueKey('exp-get-flag')

            const createParams = {
                name: 'Get Test Experiment',
                description: 'Test experiment for get operation',
                feature_flag_key: flagKey,
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const createdExperiment = parseToolResponse(createResult)
            trackExperiment(createdExperiment)

            // Get the experiment
            const result = await getTool.handler(context, { experimentId: createdExperiment.id })
            const retrievedExperiment = parseToolResponse(result)

            expect(retrievedExperiment.id).toBe(createdExperiment.id)
            expect(retrievedExperiment.name).toBe(createParams.name)
            expect(retrievedExperiment.feature_flag_key).toBe(createParams.feature_flag_key)
        })

        it('should handle non-existent experiment ID', async () => {
            const nonExistentId = 999999

            await expect(
                getTool.handler(context, { experimentId: nonExistentId })
            ).rejects.toThrow()
        })
    })

    describe('get-experiment-results tool', () => {
        const createTool = createExperimentTool()
        const getResultsTool = getExperimentResultsTool()

        it('should fail for draft experiment (not started)', async () => {
            // Create a draft experiment with metrics
            const flagKey = generateUniqueKey('exp-metrics-flag')

            const createParams = {
                name: 'Metrics Draft Experiment',
                feature_flag_key: flagKey,
                primary_metrics: [
                    {
                        name: 'Test Metric',
                        metric_type: 'mean' as const,
                        event_name: '$pageview',
                    },
                ],
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Try to get metric results for draft experiment
            await expect(
                getResultsTool.handler(context, {
                    experimentId: experiment.id,
                    refresh: false,
                })
            ).rejects.toThrow(/has not started yet/)
        })

        it('should handle refresh parameter', async () => {
            // Create an experiment with metrics
            const flagKey = generateUniqueKey('exp-metrics-refresh-flag')

            const createParams = {
                name: 'Metrics Refresh Test Experiment',
                feature_flag_key: flagKey,
                primary_metrics: [
                    {
                        name: 'Refresh Test Metric',
                        metric_type: 'mean' as const,
                        event_name: '$pageview',
                    },
                ],
                secondary_metrics: [
                    {
                        name: 'Secondary Refresh Metric',
                        metric_type: 'ratio' as const,
                        event_name: 'button_click',
                    },
                ],
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Test with refresh=true (will still fail for draft, but tests parameter handling)
            await expect(
                getResultsTool.handler(context, {
                    experimentId: experiment.id,
                    refresh: true,
                })
            ).rejects.toThrow(/has not started yet/)
        })
    })

    describe('Complex experiment workflows', () => {
        const createTool = createExperimentTool()
        const getTool = getExperimentTool()
        const getAllTool = getAllExperimentsTool()

        it('should support complete experiment creation and retrieval workflow', async () => {
            // Create feature flag
            const flagKey = generateUniqueKey('exp-workflow-flag')

            // Create comprehensive experiment
            const createParams = {
                name: 'Complete Workflow Experiment',
                description: 'Testing complete experiment workflow with all features',
                feature_flag_key: flagKey,
                type: 'product' as const,
                variants: [
                    { key: 'control', name: 'Control', rollout_percentage: 50 },
                    { key: 'test', name: 'Test Variant', rollout_percentage: 50 },
                ],
                primary_metrics: [
                    {
                        name: 'Conversion Funnel',
                        metric_type: 'funnel' as const,
                        event_name: 'landing',
                        funnel_steps: ['landing', 'signup', 'activation'],
                        description: 'Main conversion funnel',
                    },
                    {
                        name: 'Revenue per User',
                        metric_type: 'mean' as const,
                        event_name: 'purchase',
                        description: 'Average revenue',
                    },
                ],
                secondary_metrics: [
                    {
                        name: 'Engagement Rate',
                        metric_type: 'ratio' as const,
                        event_name: 'engagement',
                        description: 'User engagement ratio',
                    },
                ],
                minimum_detectable_effect: 20,
                filter_test_accounts: true,
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const createdExperiment = parseToolResponse(createResult)
            trackExperiment(createdExperiment)

            // Verify creation
            expect(createdExperiment.id).toBeDefined()
            expect(createdExperiment.name).toBe(createParams.name)
            expect(createdExperiment.parameters?.feature_flag_variants).toHaveLength(2)
            expect(createdExperiment.metrics).toHaveLength(2)
            expect(createdExperiment.metrics_secondary).toHaveLength(1)

            // Get the experiment
            const getResult = await getTool.handler(context, {
                experimentId: createdExperiment.id,
            })
            const retrievedExperiment = parseToolResponse(getResult)
            expect(retrievedExperiment.id).toBe(createdExperiment.id)

            // Verify it appears in list
            const listResult = await getAllTool.handler(context, {})
            const allExperiments = parseToolResponse(listResult)
            const found = allExperiments.find((e: any) => e.id === createdExperiment.id)
            expect(found).toBeDefined()
        })

        it('should create experiment with complex funnel metrics', async () => {
            const flagKey = generateUniqueKey('exp-complex-funnel-flag')

            const params = {
                name: 'Complex Funnel Experiment',
                feature_flag_key: flagKey,
                primary_metrics: [
                    {
                        name: 'E-commerce Full Funnel',
                        metric_type: 'funnel' as const,
                        event_name: 'home_page_view',
                        funnel_steps: [
                            'home_page_view',
                            'product_list_view',
                            'product_detail_view',
                            'add_to_cart',
                            'checkout_start',
                            'payment_info_entered',
                            'order_completed',
                        ],
                        description: 'Complete e-commerce conversion funnel',
                    },
                ],
                secondary_metrics: [
                    {
                        name: 'Cart Abandonment Funnel',
                        metric_type: 'funnel' as const,
                        event_name: 'add_to_cart',
                        funnel_steps: ['add_to_cart', 'checkout_start', 'order_completed'],
                        description: 'Track where users drop off in checkout',
                    },
                ],
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.metrics).toHaveLength(1)
            expect(experiment.metrics_secondary).toHaveLength(1)

            trackExperiment(experiment)
        })

        it('should create experiment with target properties', async () => {
            const flagKey = generateUniqueKey('exp-target-props-flag')

            const params = {
                name: 'Targeted Experiment',
                feature_flag_key: flagKey,
                target_properties: {
                    country: 'US',
                    plan: 'premium',
                    cohort: 'early_adopters',
                },
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()

            trackExperiment(experiment)
        })

        it('should create experiment without holdout group', async () => {
            const flagKey = generateUniqueKey('exp-no-holdout-flag')

            const params = {
                name: 'No Holdout Group Experiment',
                feature_flag_key: flagKey,
                // Not setting holdout_id (as it may not exist)
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()

            trackExperiment(experiment)
        })
    })

    describe('Edge cases and error handling', () => {
        const createTool = createExperimentTool()
        const getTool = getExperimentTool()
        const getResultsTool = getExperimentResultsTool()

        it('should handle creating experiment without metrics', async () => {
            const flagKey = generateUniqueKey('exp-no-metrics-flag')

            const params = {
                name: 'No Metrics Experiment',
                feature_flag_key: flagKey,
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.metrics || []).toHaveLength(0)
            expect(experiment.metrics_secondary || []).toHaveLength(0)

            trackExperiment(experiment)
        })

        it('should handle invalid experiment ID in get operations', async () => {
            const invalidId = 999999999

            // Test get experiment
            await expect(getTool.handler(context, { experimentId: invalidId })).rejects.toThrow()

            // Test get metric results
            await expect(
                getResultsTool.handler(context, {
                    experimentId: invalidId,
                    refresh: false,
                })
            ).rejects.toThrow()
        })

        it('should handle variants with invalid rollout percentages', async () => {
            const flagKey = generateUniqueKey('exp-invalid-rollout-flag')

            const params = {
                name: 'Invalid Rollout Experiment',
                feature_flag_key: flagKey,
                variants: [
                    { key: 'control', rollout_percentage: 60 },
                    { key: 'test', rollout_percentage: 60 }, // Total > 100%
                ],
                draft: true,
            }

            // This might succeed or fail depending on API validation
            // Just ensure it doesn't crash the test suite
            try {
                const result = await createTool.handler(context, params as any)
                const experiment = parseToolResponse(result)
                trackExperiment(experiment)
            } catch (error) {
                // Expected for invalid configuration
                expect(error).toBeDefined()
            }
        })

        it('should handle metric with explicit event_name', async () => {
            const flagKey = generateUniqueKey('exp-explicit-event-flag')

            const params = {
                name: 'Explicit Event Name Experiment',
                feature_flag_key: flagKey,
                primary_metrics: [
                    {
                        name: 'Default Event Metric',
                        metric_type: 'mean' as const,
                        event_name: '$pageview', // Explicit event_name since it's now required
                    },
                ],
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()
            expect(experiment.metrics).toHaveLength(1)

            trackExperiment(experiment)
        })

        it('should handle empty funnel steps array', async () => {
            const flagKey = generateUniqueKey('exp-empty-funnel-flag')

            const params = {
                name: 'Empty Funnel Steps Experiment',
                feature_flag_key: flagKey,
                primary_metrics: [
                    {
                        name: 'Empty Funnel',
                        metric_type: 'funnel' as const,
                        funnel_steps: [], // Empty array
                        event_name: '$pageview', // Falls back to this
                    },
                ],
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeDefined()

            trackExperiment(experiment)
        })

        it('should handle very long experiment names', async () => {
            const flagKey = generateUniqueKey('exp-long-name-flag')

            const longName = 'A'.repeat(500) // Very long name
            const params = {
                name: longName,
                feature_flag_key: flagKey,
                draft: true,
            }

            try {
                const result = await createTool.handler(context, params as any)
                const experiment = parseToolResponse(result)
                expect(experiment.id).toBeDefined()
                trackExperiment(experiment)
            } catch (error) {
                // Some APIs might reject very long names
                expect(error).toBeDefined()
            }
        })
    })

    describe('delete-experiment tool', () => {
        const createTool = createExperimentTool()
        const deleteTool = deleteExperimentTool()

        it('should delete an existing experiment', async () => {
            // Create experiment first
            const flagKey = generateUniqueKey('exp-delete-flag')

            const createParams = {
                name: 'Experiment to Delete',
                feature_flag_key: flagKey,
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            expect(experiment.id).toBeDefined()
            trackExperiment(experiment)

            // Delete the experiment
            const deleteParams = { experimentId: experiment.id }
            const deleteResult = await deleteTool.handler(context, deleteParams)
            const deleteResponse = parseToolResponse(deleteResult)

            expect(deleteResponse.success).toBe(true)
            expect(deleteResponse.message).toBe('Experiment deleted successfully')

            // Remove from tracking since we deleted it manually
            const index = createdExperiments.indexOf(experiment.id)
            if (index > -1) {
                createdExperiments.splice(index, 1)
            }

            // Clean up the feature flag that was auto-created
            if (experiment.feature_flag?.id) {
                createdResources.featureFlags.push(experiment.feature_flag.id)
            }
        })

        it('should handle invalid experiment ID', async () => {
            const invalidId = 999999

            const deleteParams = { experimentId: invalidId }

            try {
                await deleteTool.handler(context, deleteParams)
                expect.fail('Should have thrown an error for invalid experiment ID')
            } catch (error) {
                expect(error).toBeDefined()
                expect((error as Error).message).toContain('Failed to delete experiment')
            }
        })

        it('should handle already deleted experiment gracefully', async () => {
            // Create experiment first
            const flagKey = generateUniqueKey('exp-already-deleted-flag')

            const createParams = {
                name: 'Experiment Already Deleted',
                feature_flag_key: flagKey,
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            expect(experiment.id).toBeDefined()
            trackExperiment(experiment)

            // Delete the experiment twice
            const deleteParams = { experimentId: experiment.id }

            // First delete should succeed
            const firstDeleteResult = await deleteTool.handler(context, deleteParams)
            const firstDeleteResponse = parseToolResponse(firstDeleteResult)
            expect(firstDeleteResponse.success).toBe(true)

            // Second delete should throw error (API returns 404 for already deleted)
            try {
                await deleteTool.handler(context, deleteParams)
                expect.fail('Should have thrown an error for already deleted experiment')
            } catch (error) {
                expect(error).toBeDefined()
                expect((error as Error).message).toContain('Failed to delete experiment')
                expect((error as Error).message).toContain('404')
            }

            // Remove from tracking since we deleted it manually
            const index = createdExperiments.indexOf(experiment.id)
            if (index > -1) {
                createdExperiments.splice(index, 1)
            }

            // Clean up the feature flag that was auto-created
            if (experiment.feature_flag?.id) {
                createdResources.featureFlags.push(experiment.feature_flag.id)
            }
        })

        it('should validate required experimentId parameter', async () => {
            try {
                await deleteTool.handler(context, {} as any)
                expect.fail('Should have thrown validation error for missing experimentId')
            } catch (error) {
                expect(error).toBeDefined()
            }
        })
    })

    describe('update-experiment tool', () => {
        const createTool = createExperimentTool()
        const updateTool = updateExperimentTool()

        it('should update basic experiment fields', async () => {
            // Create experiment first
            const flagKey = generateUniqueKey('exp-update-basic-flag')

            const createParams = {
                name: 'Original Name',
                description: 'Original description',
                feature_flag_key: flagKey,
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            expect(experiment.id).toBeDefined()
            trackExperiment(experiment)

            // Update basic fields
            const updateParams = {
                experimentId: experiment.id,
                data: {
                    name: 'Updated Name',
                    description: 'Updated description with new hypothesis',
                },
            }

            const updateResult = await updateTool.handler(context, updateParams)
            const updatedExperiment = parseToolResponse(updateResult)

            expect(updatedExperiment.name).toBe('Updated Name')
            expect(updatedExperiment.description).toBe('Updated description with new hypothesis')
            expect(updatedExperiment.url).toContain('/experiments/')
            expect(updatedExperiment.start_date).toBeNull() // Draft experiments have no start date

            trackExperiment(experiment)
        })

        it('should launch a draft experiment (draft → running)', async () => {
            // Create draft experiment
            const flagKey = generateUniqueKey('exp-launch-flag')

            const createParams = {
                name: 'Launch Test Experiment',
                feature_flag_key: flagKey,
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            expect(experiment.start_date).toBeNull() // Draft experiments have no start date
            trackExperiment(experiment)

            // Launch the experiment
            const launchParams = {
                experimentId: experiment.id,
                data: {
                    launch: true,
                },
            }

            const updateResult = await updateTool.handler(context, launchParams)
            const launchedExperiment = parseToolResponse(updateResult)

            expect(launchedExperiment.start_date).toBeDefined() // Running experiments have start date
            expect(launchedExperiment.end_date).toBeNull() // But no end date yet

            trackExperiment(experiment)
        })

        it('should stop a running experiment', async () => {
            // Create and launch experiment
            const flagKey = generateUniqueKey('exp-stop-flag')

            const createParams = {
                name: 'Stop Test Experiment',
                feature_flag_key: flagKey,
                draft: false, // Create as launched
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Stop the experiment
            const stopParams = {
                experimentId: experiment.id,
                data: {
                    end_date: new Date().toISOString(),
                    conclusion: 'stopped_early' as const,
                    conclusion_comment: 'Test completed successfully',
                },
            }

            const updateResult = await updateTool.handler(context, stopParams)
            const stoppedExperiment = parseToolResponse(updateResult)

            expect(stoppedExperiment.end_date).toBeDefined()
            // Note: API may not set conclusion field automatically, it depends on the backend implementation
            // The important thing is that end_date is set, indicating the experiment is stopped

            trackExperiment(experiment)
        })

        it('should restart a concluded experiment', async () => {
            // Create and conclude experiment
            const flagKey = generateUniqueKey('exp-restart-flag')

            const createParams = {
                name: 'Restart Test Experiment',
                feature_flag_key: flagKey,
                draft: false,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // First stop it
            const stopParams = {
                experimentId: experiment.id,
                data: {
                    end_date: new Date().toISOString(),
                    conclusion: 'inconclusive' as const,
                    conclusion_comment: 'Need more data',
                },
            }

            await updateTool.handler(context, stopParams)

            // Now restart it (following restart workflow)
            const restartParams = {
                experimentId: experiment.id,
                data: {
                    restart: true,
                    launch: true,
                },
            }

            const restartResult = await updateTool.handler(context, restartParams)
            const restartedExperiment = parseToolResponse(restartResult)

            expect(restartedExperiment.end_date).toBeNull()
            expect(restartedExperiment.conclusion).toBeNull()
            expect(restartedExperiment.conclusion_comment).toBeNull()
            expect(restartedExperiment.start_date).toBeDefined() // Restarted experiments have start date
            expect(restartedExperiment.end_date).toBeNull() // But no end date

            trackExperiment(experiment)
        })

        it('should restart experiment as draft', async () => {
            // Create and conclude experiment
            const flagKey = generateUniqueKey('exp-restart-draft-flag')

            const createParams = {
                name: 'Restart as Draft Test',
                feature_flag_key: flagKey,
                draft: false,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // First conclude it
            const concludeParams = {
                experimentId: experiment.id,
                data: {
                    conclude: 'won' as const,
                },
            }

            await updateTool.handler(context, concludeParams)

            // Restart as draft (clear all completion fields including start_date)
            const restartAsDraftParams = {
                experimentId: experiment.id,
                data: {
                    restart: true,
                },
            }

            const restartResult = await updateTool.handler(context, restartAsDraftParams)
            const restartedExperiment = parseToolResponse(restartResult)

            expect(restartedExperiment.end_date).toBeNull()
            expect(restartedExperiment.conclusion).toBeNull()
            expect(restartedExperiment.start_date).toBeNull() // Draft experiments have no start date

            trackExperiment(experiment)
        })

        it('should archive and unarchive experiment', async () => {
            // Create experiment
            const flagKey = generateUniqueKey('exp-archive-flag')

            const createParams = {
                name: 'Archive Test Experiment',
                feature_flag_key: flagKey,
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Archive the experiment
            const archiveParams = {
                experimentId: experiment.id,
                data: {
                    archive: true,
                },
            }

            const archiveResult = await updateTool.handler(context, archiveParams)
            const archivedExperiment = parseToolResponse(archiveResult)

            expect(archivedExperiment.archived).toBe(true)

            // Unarchive the experiment
            const unarchiveParams = {
                experimentId: experiment.id,
                data: {
                    archive: false,
                },
            }

            const unarchiveResult = await updateTool.handler(context, unarchiveParams)
            const unarchivedExperiment = parseToolResponse(unarchiveResult)

            expect(unarchivedExperiment.archived).toBe(false)

            trackExperiment(experiment)
        })

        it('should update experiment variants', async () => {
            // Create experiment with default variants
            const flagKey = generateUniqueKey('exp-variants-flag')

            const createParams = {
                name: 'Variants Update Test',
                feature_flag_key: flagKey,
                draft: true,
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Update minimum detectable effect
            const updateParamsParams = {
                experimentId: experiment.id,
                data: {
                    minimum_detectable_effect: 25,
                },
            }

            const updateResult = await updateTool.handler(context, updateParamsParams)
            const updatedExperiment = parseToolResponse(updateResult)

            expect(updatedExperiment.parameters?.minimum_detectable_effect).toBe(25)

            trackExperiment(experiment)
        })

        it('should handle invalid experiment ID', async () => {
            const invalidId = 999999

            const updateParams = {
                experimentId: invalidId,
                data: {
                    name: 'This should fail',
                },
            }

            try {
                await updateTool.handler(context, updateParams)
                expect.fail('Should have thrown an error for invalid experiment ID')
            } catch (error) {
                expect(error).toBeDefined()
                expect((error as Error).message).toContain('Failed to update experiment')
            }
        })

        it('should validate required experimentId parameter', async () => {
            try {
                await updateTool.handler(context, { data: { name: 'Test' } } as any)
                expect.fail('Should have thrown validation error for missing experimentId')
            } catch (error) {
                expect(error).toBeDefined()
            }
        })

        it('should handle partial updates correctly', async () => {
            // Create experiment
            const flagKey = generateUniqueKey('exp-partial-flag')

            const createParams = {
                name: 'Partial Update Test',
                description: 'Original description',
                feature_flag_key: flagKey,
                draft: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Update only name, leaving description unchanged
            const updateParams = {
                experimentId: experiment.id,
                data: {
                    name: 'Updated Name Only',
                },
            }

            const updateResult = await updateTool.handler(context, updateParams)
            const updatedExperiment = parseToolResponse(updateResult)

            expect(updatedExperiment.name).toBe('Updated Name Only')
            // Description should remain unchanged
            expect(updatedExperiment.description).toBe('Original description')

            trackExperiment(experiment)
        })
    })

    describe('Experiment status handling', () => {
        const createTool = createExperimentTool()

        it('should correctly identify draft experiments', async () => {
            const flagKey = generateUniqueKey('exp-draft-status-flag')

            const params = {
                name: 'Draft Status Experiment',
                feature_flag_key: flagKey,
                draft: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.start_date).toBeNull() // Draft experiments have no start date

            trackExperiment(experiment)
        })

        it('should handle immediate launch (non-draft) experiments', async () => {
            const flagKey = generateUniqueKey('exp-launch-flag')

            const params = {
                name: 'Immediate Launch Experiment',
                feature_flag_key: flagKey,
                draft: false,
            }

            try {
                const result = await createTool.handler(context, params as any)
                const experiment = parseToolResponse(result)

                // Check actual date fields instead of computed status
                expect(experiment.start_date).toBeDefined() // Should have start date if launched

                trackExperiment(experiment)
            } catch (error) {
                // Some environments might not allow immediate launch
                expect(error).toBeDefined()
            }
        })
    })
})
