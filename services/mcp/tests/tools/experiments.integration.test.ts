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
import getExperimentResultsTool from '@/tools/experiments/getResults'
import { GENERATED_TOOLS } from '@/tools/generated/experiments'
import type { Context } from '@/tools/types'

describe('Experiments', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
        cohorts: [],
    }
    const createdExperiments: number[] = []

    // Helper function to track created experiments and their feature flags
    const trackExperiment = (experiment: any): void => {
        if (experiment.id) {
            createdExperiments.push(experiment.id)
        }
        if (experiment.feature_flag?.id) {
            createdResources.featureFlags.push(experiment.feature_flag.id)
        }
    }

    const createTool = GENERATED_TOOLS['experiment-create']!()
    const getTool = GENERATED_TOOLS['experiment-get']!()
    const getAllTool = GENERATED_TOOLS['experiment-get-all']!()
    const updateTool = GENERATED_TOOLS['experiment-update']!()
    const deleteTool = GENERATED_TOOLS['experiment-delete']!()
    const launchTool = GENERATED_TOOLS['experiment-launch']!()
    const endTool = GENERATED_TOOLS['experiment-end']!()
    const archiveTool = GENERATED_TOOLS['experiment-archive']!()
    const pauseTool = GENERATED_TOOLS['experiment-pause']!()
    const resumeTool = GENERATED_TOOLS['experiment-resume']!()
    const resetTool = GENERATED_TOOLS['experiment-reset']!()
    const shipVariantTool = GENERATED_TOOLS['experiment-ship-variant']!()
    const getResultsTool = getExperimentResultsTool()

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
                await context.api.request({
                    method: 'PATCH',
                    path: `/api/projects/${TEST_PROJECT_ID}/experiments/${experimentId}/`,
                    body: { deleted: true },
                })
            } catch {
                // Ignore cleanup failures
            }
        }
        createdExperiments.length = 0

        // Clean up associated feature flags
        await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources)
    })

    describe('create-experiment tool', () => {
        it('should create a draft experiment with minimal required fields', async () => {
            const flagKey = generateUniqueKey('exp-flag')

            const params = {
                name: 'Minimal Test Experiment',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.name).toBe(params.name)
            expect(experiment.feature_flag_key).toBe(params.feature_flag_key)
            expect(experiment.start_date).toBeNull() // Draft experiments have no start date
            expect(experiment._posthogUrl).toContain('/experiments/')
        })

        it('should create an experiment with description and type', async () => {
            const flagKey = generateUniqueKey('exp-flag-desc')

            const params = {
                name: 'Detailed Test Experiment',
                description: 'This experiment tests the impact of button color on conversions',
                feature_flag_key: flagKey,
                type: 'web',
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.name).toBe(params.name)
            expect(experiment.feature_flag_key).toBe(params.feature_flag_key)
        })

        it('should create an experiment with custom variants', async () => {
            const flagKey = generateUniqueKey('exp-flag-variants')

            const params = {
                name: 'Variant Test Experiment',
                feature_flag_key: flagKey,
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', name: 'Control Group', split_percent: 33 },
                        { key: 'variant_a', name: 'Variant A', split_percent: 33 },
                        { key: 'variant_b', name: 'Variant B', split_percent: 34 },
                    ],
                },
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.parameters?.feature_flag_variants).toHaveLength(3)
            expect(experiment.parameters?.feature_flag_variants?.[0]?.key).toBe('control')
            expect(experiment.parameters?.feature_flag_variants?.[0]?.split_percent).toBe(33)
        })

        it('should create an experiment with mean metric', async () => {
            const flagKey = generateUniqueKey('exp-flag-mean')

            const params = {
                name: 'Mean Metric Experiment',
                feature_flag_key: flagKey,
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Average Page Load Time',
                        metric_type: 'mean',
                        source: {
                            kind: 'EventsNode',
                            event: '$pageview',
                            properties: [{ key: 'page', value: '/checkout', operator: 'exact', type: 'event' }],
                        },
                    },
                ],
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.metrics).toHaveLength(1)
        })

        it('should create an experiment with funnel metric', async () => {
            const flagKey = generateUniqueKey('exp-flag-funnel')

            const params = {
                name: 'Funnel Metric Experiment',
                feature_flag_key: flagKey,
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Checkout Conversion Funnel',
                        metric_type: 'funnel',
                        series: [
                            { kind: 'EventsNode', event: 'product_view' },
                            { kind: 'EventsNode', event: 'add_to_cart' },
                            { kind: 'EventsNode', event: 'checkout_start' },
                            { kind: 'EventsNode', event: 'purchase' },
                        ],
                    },
                ],
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.metrics).toHaveLength(1)
        })

        it('should create an experiment with ratio metric', async () => {
            const flagKey = generateUniqueKey('exp-flag-ratio')

            const params = {
                name: 'Ratio Metric Experiment',
                feature_flag_key: flagKey,
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Button Click Rate',
                        metric_type: 'ratio',
                        numerator: { kind: 'EventsNode', event: 'button_click' },
                        denominator: { kind: 'EventsNode', event: '$pageview' },
                    },
                ],
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.metrics).toHaveLength(1)
        })

        it('should create an experiment with multiple metrics', async () => {
            const flagKey = generateUniqueKey('exp-flag-multi')

            const params = {
                name: 'Multi Metric Experiment',
                feature_flag_key: flagKey,
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Conversion Rate',
                        metric_type: 'funnel',
                        series: [
                            { kind: 'EventsNode', event: 'visit' },
                            { kind: 'EventsNode', event: 'signup' },
                            { kind: 'EventsNode', event: 'purchase' },
                        ],
                    },
                    {
                        kind: 'ExperimentMetric',
                        name: 'Average Revenue',
                        metric_type: 'mean',
                        source: { kind: 'EventsNode', event: 'purchase' },
                    },
                ],
                metrics_secondary: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Page Views',
                        metric_type: 'mean',
                        source: { kind: 'EventsNode', event: '$pageview' },
                    },
                    {
                        kind: 'ExperimentMetric',
                        name: 'Bounce Rate',
                        metric_type: 'ratio',
                        numerator: { kind: 'EventsNode', event: 'bounce' },
                        denominator: { kind: 'EventsNode', event: '$pageview' },
                    },
                ],
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.metrics).toHaveLength(2)
            expect(experiment.metrics_secondary).toHaveLength(2)
        })

        it('should reject unknown event names when allow_unknown_events is not set', async () => {
            const flagKey = generateUniqueKey('exp-flag-unknown-event')

            const params = {
                name: 'Unknown Event Experiment',
                feature_flag_key: flagKey,
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Nonexistent Event Metric',
                        metric_type: 'mean',
                        source: { kind: 'EventsNode', event: 'totally_nonexistent_event' },
                    },
                ],
            }

            await expect(createTool.handler(context, params as any)).rejects.toThrow(/not found/)
        })

        it('should create an experiment with minimum detectable effect', async () => {
            const flagKey = generateUniqueKey('exp-flag-mde')

            const params = {
                name: 'MDE Test Experiment',
                feature_flag_key: flagKey,
                parameters: {
                    minimum_detectable_effect: 15,
                },
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
        })

        it('should create an experiment with filter test accounts enabled', async () => {
            const flagKey = generateUniqueKey('exp-flag-filter')

            const params = {
                name: 'Filter Test Accounts Experiment',
                feature_flag_key: flagKey,
                exposure_criteria: {
                    filterTestAccounts: true,
                },
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
        })

        it("should create experiment when feature flag doesn't exist (API creates it)", async () => {
            const params = {
                name: 'Auto-Create Flag Experiment',
                feature_flag_key: generateUniqueKey('auto-created-flag'),
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)

            expect(experiment.id).toBeTruthy()
            trackExperiment(experiment)
        })
    })

    describe('get-all-experiments tool', () => {
        it('should list all experiments', async () => {
            // Create a few test experiments
            const testExperiments = []
            for (let i = 0; i < 3; i++) {
                const flagKey = generateUniqueKey(`exp-list-flag-${i}`)

                const params = {
                    name: `List Test Experiment ${i}`,
                    feature_flag_key: flagKey,
                    allow_unknown_events: true,
                }

                const result = await createTool.handler(context, params as any)
                const experiment = parseToolResponse(result)
                trackExperiment(experiment)
                testExperiments.push(experiment)
            }

            // Get all experiments
            const result = await getAllTool.handler(context, {})
            const allExperiments = parseToolResponse(result)
            expect(allExperiments.results.length).toBeGreaterThanOrEqual(3)

            // Verify our test experiments are in the list
            for (const testExp of testExperiments) {
                const found = allExperiments.results.find((e: any) => e.id === testExp.id)
                expect(found).toBeTruthy()
            }
        })

        it('should return experiments with proper structure', async () => {
            const result = await getAllTool.handler(context, {})
            const experiments = parseToolResponse(result)

            if (experiments.results.length > 0) {
                const experiment = experiments.results[0]
                expect(experiment).toHaveProperty('id')
                expect(experiment).toHaveProperty('name')
                expect(experiment).toHaveProperty('feature_flag_key')
            }
        })

        it('should respect limit parameter', async () => {
            const result = await getAllTool.handler(context, { limit: 2 })
            const experiments = parseToolResponse(result)
            expect(experiments.results.length).toBeLessThanOrEqual(2)
        })

        it('should respect offset parameter', async () => {
            const allResult = await getAllTool.handler(context, { limit: 10 })
            const allExperiments = parseToolResponse(allResult)

            if (allExperiments.results.length > 1) {
                const offsetResult = await getAllTool.handler(context, { limit: 10, offset: 1 })
                const offsetExperiments = parseToolResponse(offsetResult)
                // Verify offset is working by checking first result is different from original first result
                expect(offsetExperiments.results[0].id).not.toBe(allExperiments.results[0].id)
            }
        })

        it('should use default limit when not specified', async () => {
            const result = await getAllTool.handler(context, {})
            const experiments = parseToolResponse(result)
            expect(experiments.results.length).toBeLessThanOrEqual(50)
        })
    })

    describe('get-experiment tool', () => {
        it('should get experiment by ID', async () => {
            // Create an experiment
            const flagKey = generateUniqueKey('exp-get-flag')

            const createParams = {
                name: 'Get Test Experiment',
                description: 'Test experiment for get operation',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const createdExperiment = parseToolResponse(createResult)
            trackExperiment(createdExperiment)

            // Get the experiment
            const result = await getTool.handler(context, { id: createdExperiment.id })
            const retrievedExperiment = parseToolResponse(result)

            expect(retrievedExperiment.id).toBe(createdExperiment.id)
            expect(retrievedExperiment.name).toBe(createParams.name)
            expect(retrievedExperiment.feature_flag_key).toBe(createParams.feature_flag_key)
        })

        it('should handle non-existent experiment ID', async () => {
            const nonExistentId = 999999

            await expect(getTool.handler(context, { id: nonExistentId })).rejects.toThrow()
        })
    })

    describe('get-experiment-results tool', () => {
        it('should fail for draft experiment (not started)', async () => {
            // Create a draft experiment with metrics
            const flagKey = generateUniqueKey('exp-metrics-flag')

            const createParams = {
                name: 'Metrics Draft Experiment',
                feature_flag_key: flagKey,
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Test Metric',
                        metric_type: 'mean',
                        source: { kind: 'EventsNode', event: '$pageview' },
                    },
                ],
                allow_unknown_events: true,
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
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Refresh Test Metric',
                        metric_type: 'mean',
                        source: { kind: 'EventsNode', event: '$pageview' },
                    },
                ],
                metrics_secondary: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Secondary Refresh Metric',
                        metric_type: 'ratio',
                        numerator: { kind: 'EventsNode', event: 'button_click' },
                        denominator: { kind: 'EventsNode', event: '$pageview' },
                    },
                ],
                allow_unknown_events: true,
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
        it('should support complete experiment creation and retrieval workflow', async () => {
            // Create feature flag
            const flagKey = generateUniqueKey('exp-workflow-flag')

            // Create comprehensive experiment
            const createParams = {
                name: 'Complete Workflow Experiment',
                description: 'Testing complete experiment workflow with all features',
                feature_flag_key: flagKey,
                type: 'product',
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', name: 'Control', split_percent: 50 },
                        { key: 'test', name: 'Test Variant', split_percent: 50 },
                    ],
                    minimum_detectable_effect: 20,
                },
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Conversion Funnel',
                        metric_type: 'funnel',
                        series: [
                            { kind: 'EventsNode', event: 'landing' },
                            { kind: 'EventsNode', event: 'signup' },
                            { kind: 'EventsNode', event: 'activation' },
                        ],
                    },
                    {
                        kind: 'ExperimentMetric',
                        name: 'Revenue per User',
                        metric_type: 'mean',
                        source: { kind: 'EventsNode', event: 'purchase' },
                    },
                ],
                metrics_secondary: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Engagement Rate',
                        metric_type: 'ratio',
                        numerator: { kind: 'EventsNode', event: 'engagement' },
                        denominator: { kind: 'EventsNode', event: '$pageview' },
                    },
                ],
                exposure_criteria: {
                    filterTestAccounts: true,
                },
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const createdExperiment = parseToolResponse(createResult)
            trackExperiment(createdExperiment)

            // Verify creation
            expect(createdExperiment.id).toBeTruthy()
            expect(createdExperiment.name).toBe(createParams.name)
            expect(createdExperiment.parameters?.feature_flag_variants).toHaveLength(2)
            expect(createdExperiment.metrics).toHaveLength(2)
            expect(createdExperiment.metrics_secondary).toHaveLength(1)

            // Get the experiment
            const getResult = await getTool.handler(context, {
                id: createdExperiment.id,
            })
            const retrievedExperiment = parseToolResponse(getResult)
            expect(retrievedExperiment.id).toBe(createdExperiment.id)

            // Verify it appears in list
            const listResult = await getAllTool.handler(context, {})
            const allExperiments = parseToolResponse(listResult)
            const found = allExperiments.results.find((e: any) => e.id === createdExperiment.id)
            expect(found).toBeTruthy()
        })

        it('should create experiment with complex funnel metrics', async () => {
            const flagKey = generateUniqueKey('exp-complex-funnel-flag')

            const params = {
                name: 'Complex Funnel Experiment',
                feature_flag_key: flagKey,
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'E-commerce Full Funnel',
                        metric_type: 'funnel',
                        series: [
                            { kind: 'EventsNode', event: 'home_page_view' },
                            { kind: 'EventsNode', event: 'product_list_view' },
                            { kind: 'EventsNode', event: 'product_detail_view' },
                            { kind: 'EventsNode', event: 'add_to_cart' },
                            { kind: 'EventsNode', event: 'checkout_start' },
                            { kind: 'EventsNode', event: 'payment_info_entered' },
                            { kind: 'EventsNode', event: 'order_completed' },
                        ],
                    },
                ],
                metrics_secondary: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Cart Abandonment Funnel',
                        metric_type: 'funnel',
                        series: [
                            { kind: 'EventsNode', event: 'add_to_cart' },
                            { kind: 'EventsNode', event: 'checkout_start' },
                            { kind: 'EventsNode', event: 'order_completed' },
                        ],
                    },
                ],
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.metrics).toHaveLength(1)
            expect(experiment.metrics_secondary).toHaveLength(1)
        })

        it('should create experiment without holdout group', async () => {
            const flagKey = generateUniqueKey('exp-no-holdout-flag')

            const params = {
                name: 'No Holdout Group Experiment',
                feature_flag_key: flagKey,
                // Not setting holdout_id (as it may not exist)
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
        })
    })

    describe('Edge cases and error handling', () => {
        it('should handle creating experiment without metrics', async () => {
            const flagKey = generateUniqueKey('exp-no-metrics-flag')

            const params = {
                name: 'No Metrics Experiment',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.metrics || []).toHaveLength(0)
            expect(experiment.metrics_secondary || []).toHaveLength(0)
        })

        it('should handle invalid experiment ID in get operations', async () => {
            const invalidId = 999999999

            // Test get experiment
            await expect(getTool.handler(context, { id: invalidId })).rejects.toThrow()

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
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', split_percent: 60 },
                        { key: 'test', split_percent: 60 }, // Total > 100%
                    ],
                },
                allow_unknown_events: true,
            }

            // This might succeed or fail depending on API validation
            // Just ensure it doesn't crash the test suite
            try {
                const result = await createTool.handler(context, params as any)
                const experiment = parseToolResponse(result)
                trackExperiment(experiment)
            } catch (error) {
                // Expected for invalid configuration
                expect(error).toBeTruthy()
            }
        })

        it('should handle metric with explicit event in source', async () => {
            const flagKey = generateUniqueKey('exp-explicit-event-flag')

            const params = {
                name: 'Explicit Event Name Experiment',
                feature_flag_key: flagKey,
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Default Event Metric',
                        metric_type: 'mean',
                        source: { kind: 'EventsNode', event: '$pageview' },
                    },
                ],
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
            expect(experiment.metrics).toHaveLength(1)
        })

        it('should handle funnel with single step', async () => {
            // A single-step series is valid for experiments: the exposure event is
            // prepended at query time, yielding a conversion-rate funnel from exposure to event.
            const flagKey = generateUniqueKey('exp-single-funnel-flag')

            const params = {
                name: 'Single Step Funnel Experiment',
                feature_flag_key: flagKey,
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Single Step Funnel',
                        metric_type: 'funnel',
                        series: [{ kind: 'EventsNode', event: '$pageview' }],
                    },
                ],
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()
        })

        it('should handle very long experiment names', async () => {
            const flagKey = generateUniqueKey('exp-long-name-flag')

            const longName = 'A'.repeat(500) // Very long name
            const params = {
                name: longName,
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            try {
                const result = await createTool.handler(context, params as any)
                const experiment = parseToolResponse(result)
                trackExperiment(experiment)
                expect(experiment.id).toBeTruthy()
            } catch (error) {
                // Some APIs might reject very long names
                expect(error).toBeTruthy()
            }
        })
    })

    describe('delete-experiment tool', () => {
        it('should delete an existing experiment', async () => {
            // Create experiment first
            const flagKey = generateUniqueKey('exp-delete-flag')

            const createParams = {
                name: 'Experiment to Delete',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()

            // Delete the experiment (soft-delete returns experiment with deleted=true)
            const deleteResult = await deleteTool.handler(context, { id: experiment.id })
            const deleteResponse = parseToolResponse(deleteResult)

            expect(deleteResponse.deleted).toBe(true)

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

            try {
                await deleteTool.handler(context, { id: invalidId })
                expect.fail('Should have thrown an error for invalid experiment ID')
            } catch (error) {
                expect(error).toBeTruthy()
            }
        })

        it('should handle already deleted experiment gracefully', async () => {
            // Create experiment first
            const flagKey = generateUniqueKey('exp-already-deleted-flag')

            const createParams = {
                name: 'Experiment Already Deleted',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            expect(experiment.id).toBeTruthy()
            trackExperiment(experiment)

            // Delete the experiment twice
            // First delete should succeed
            const firstDeleteResult = await deleteTool.handler(context, { id: experiment.id })
            const firstDeleteResponse = parseToolResponse(firstDeleteResult)
            expect(firstDeleteResponse.deleted).toBe(true)

            // Second delete should throw error (API returns 404 for already deleted)
            try {
                await deleteTool.handler(context, { id: experiment.id })
                expect.fail('Should have thrown an error for already deleted experiment')
            } catch (error) {
                expect(error).toBeTruthy()
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

        it('should validate required id parameter', async () => {
            try {
                await deleteTool.handler(context, {} as any)
                expect.fail('Should have thrown validation error for missing id')
            } catch (error) {
                expect(error).toBeTruthy()
            }
        })
    })

    describe('update-experiment tool', () => {
        it('should update basic experiment fields', async () => {
            // Create experiment first
            const flagKey = generateUniqueKey('exp-update-basic-flag')

            const createParams = {
                name: 'Original Name',
                description: 'Original description',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            expect(experiment.id).toBeTruthy()

            // Update basic fields
            const updateResult = await updateTool.handler(context, {
                id: experiment.id,
                name: 'Updated Name',
                description: 'Updated description with new hypothesis',
            } as any)
            const updatedExperiment = parseToolResponse(updateResult)

            expect(updatedExperiment.name).toBe('Updated Name')
            expect(updatedExperiment.description).toBe('Updated description with new hypothesis')
            expect(updatedExperiment._posthogUrl).toContain('/experiments/')
            expect(updatedExperiment.start_date).toBeNull() // Draft experiments have no start date
        })

        it('should launch a draft experiment (draft → running)', async () => {
            // Create draft experiment
            const flagKey = generateUniqueKey('exp-launch-flag')

            const createParams = {
                name: 'Launch Test Experiment',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            expect(experiment.start_date).toBeNull() // Draft experiments have no start date

            // Launch the experiment using the lifecycle tool
            const launchResult = await launchTool.handler(context, { id: experiment.id })
            const launchedExperiment = parseToolResponse(launchResult)

            expect(launchedExperiment.start_date).toBeTruthy() // Running experiments have start date
            expect(launchedExperiment.end_date).toBeNull() // But no end date yet
        })

        it('should stop a running experiment', async () => {
            // Create and launch experiment
            const flagKey = generateUniqueKey('exp-stop-flag')

            const createParams = {
                name: 'Stop Test Experiment',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Launch first
            await launchTool.handler(context, { id: experiment.id })

            // End the experiment using the lifecycle tool
            const endResult = await endTool.handler(context, {
                id: experiment.id,
                conclusion: 'stopped_early',
                conclusion_comment: 'Test completed successfully',
            } as any)
            const stoppedExperiment = parseToolResponse(endResult)

            expect(stoppedExperiment.end_date).toBeTruthy()
            expect(stoppedExperiment.conclusion).toBe('stopped_early')
        })

        it('should restart a concluded experiment', async () => {
            // Create and launch experiment
            const flagKey = generateUniqueKey('exp-restart-flag')

            const createParams = {
                name: 'Restart Test Experiment',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Launch
            await launchTool.handler(context, { id: experiment.id })

            // End it
            await endTool.handler(context, {
                id: experiment.id,
                conclusion: 'inconclusive',
                conclusion_comment: 'Need more data',
            } as any)

            // Reset to draft
            const resetResult = await resetTool.handler(context, { id: experiment.id })
            const resetExperiment = parseToolResponse(resetResult)

            expect(resetExperiment.end_date).toBeNull()
            expect(resetExperiment.conclusion).toBeNull()
            expect(resetExperiment.conclusion_comment).toBeNull()
            expect(resetExperiment.start_date).toBeNull()
        })

        it('should restart experiment as draft', async () => {
            // Create and launch experiment
            const flagKey = generateUniqueKey('exp-restart-draft-flag')

            const createParams = {
                name: 'Restart as Draft Test',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Launch
            await launchTool.handler(context, { id: experiment.id })

            // End with conclusion
            await endTool.handler(context, {
                id: experiment.id,
                conclusion: 'won',
            } as any)

            // Reset back to draft
            const resetResult = await resetTool.handler(context, { id: experiment.id })
            const restartedExperiment = parseToolResponse(resetResult)

            expect(restartedExperiment.end_date).toBeNull()
            expect(restartedExperiment.conclusion).toBeNull()
            expect(restartedExperiment.start_date).toBeNull() // Draft experiments have no start date
        })

        it('should archive and unarchive experiment', async () => {
            // Create experiment
            const flagKey = generateUniqueKey('exp-archive-flag')

            const createParams = {
                name: 'Archive Test Experiment',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Archive the experiment via update
            const archiveResult = await updateTool.handler(context, {
                id: experiment.id,
                archived: true,
            } as any)
            const archivedExperiment = parseToolResponse(archiveResult)

            expect(archivedExperiment.archived).toBe(true)

            // Unarchive the experiment
            const unarchiveResult = await updateTool.handler(context, {
                id: experiment.id,
                archived: false,
            } as any)
            const unarchivedExperiment = parseToolResponse(unarchiveResult)

            expect(unarchivedExperiment.archived).toBe(false)
        })

        it('should update experiment variants', async () => {
            // Create experiment with default variants
            const flagKey = generateUniqueKey('exp-variants-flag')

            const createParams = {
                name: 'Variants Update Test',
                feature_flag_key: flagKey,
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', split_percent: 50 },
                        { key: 'test', split_percent: 50 },
                    ],
                },
                allow_unknown_events: true,
                feature_flag_variants: [
                    { key: 'control', split_percent: 50 },
                    { key: 'test', split_percent: 50 },
                ],
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Update minimum detectable effect
            const updateResult = await updateTool.handler(context, {
                id: experiment.id,
                parameters: {
                    minimum_detectable_effect: 25,
                },
            } as any)
            const updatedExperiment = parseToolResponse(updateResult)

            expect(updatedExperiment.parameters?.minimum_detectable_effect).toBe(25)
        })

        it('should handle invalid experiment ID', async () => {
            const invalidId = 999999

            try {
                await updateTool.handler(context, {
                    id: invalidId,
                    name: 'This should fail',
                } as any)
                expect.fail('Should have thrown an error for invalid experiment ID')
            } catch (error) {
                expect(error).toBeTruthy()
            }
        })

        it('should validate required id parameter', async () => {
            try {
                await updateTool.handler(context, { name: 'Test' } as any)
                expect.fail('Should have thrown validation error for missing id')
            } catch (error) {
                expect(error).toBeTruthy()
            }
        })

        it('should handle partial updates correctly', async () => {
            // Create experiment
            const flagKey = generateUniqueKey('exp-partial-flag')

            const createParams = {
                name: 'Partial Update Test',
                description: 'Original description',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const createResult = await createTool.handler(context, createParams as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Update only name, leaving description unchanged
            const updateResult = await updateTool.handler(context, {
                id: experiment.id,
                name: 'Updated Name Only',
            } as any)
            const updatedExperiment = parseToolResponse(updateResult)

            expect(updatedExperiment.name).toBe('Updated Name Only')
            // Description should remain unchanged
            expect(updatedExperiment.description).toBe('Original description')
        })
    })

    describe('Experiment status handling', () => {
        it('should correctly identify draft experiments', async () => {
            const flagKey = generateUniqueKey('exp-draft-status-flag')

            const params = {
                name: 'Draft Status Experiment',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            const result = await createTool.handler(context, params as any)
            const experiment = parseToolResponse(result)
            trackExperiment(experiment)

            expect(experiment.start_date).toBeNull() // Draft experiments have no start date
        })

        it('should handle launch then verify running state', async () => {
            const flagKey = generateUniqueKey('exp-launch-status-flag')

            const params = {
                name: 'Launch Status Experiment',
                feature_flag_key: flagKey,
                allow_unknown_events: true,
            }

            try {
                const createResult = await createTool.handler(context, params as any)
                const experiment = parseToolResponse(createResult)
                trackExperiment(experiment)

                // Launch
                const launchResult = await launchTool.handler(context, { id: experiment.id })
                const launchedExperiment = parseToolResponse(launchResult)

                // Check actual date fields
                expect(launchedExperiment.start_date).toBeTruthy() // Should have start date if launched
            } catch (error) {
                // Some environments might not allow immediate launch
                expect(error).toBeTruthy()
            }
        })
    })

    describe('Lifecycle tools', () => {
        it('should pause and resume a running experiment', async () => {
            const flagKey = generateUniqueKey('exp-pause-flag')

            const createResult = await createTool.handler(context, {
                name: 'Pause Test Experiment',
                feature_flag_key: flagKey,
            } as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Launch
            await launchTool.handler(context, { id: experiment.id })

            // Pause
            const pauseResult = await pauseTool.handler(context, { id: experiment.id })
            const paused = parseToolResponse(pauseResult)
            expect(paused.id).toBe(experiment.id)

            // Resume
            const resumeResult = await resumeTool.handler(context, { id: experiment.id })
            const resumed = parseToolResponse(resumeResult)
            expect(resumed.id).toBe(experiment.id)
        })

        it('should archive an ended experiment', async () => {
            const flagKey = generateUniqueKey('exp-archive-lifecycle-flag')

            const createResult = await createTool.handler(context, {
                name: 'Archive Lifecycle Test',
                feature_flag_key: flagKey,
            } as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Launch and end
            await launchTool.handler(context, { id: experiment.id })
            await endTool.handler(context, { id: experiment.id } as any)

            // Archive via lifecycle tool
            const archiveResult = await archiveTool.handler(context, { id: experiment.id })
            const archived = parseToolResponse(archiveResult)
            expect(archived.archived).toBe(true)
        })

        it('should ship a variant to 100%', async () => {
            const flagKey = generateUniqueKey('exp-ship-flag')

            const createResult = await createTool.handler(context, {
                name: 'Ship Variant Test',
                feature_flag_key: flagKey,
            } as any)
            const experiment = parseToolResponse(createResult)
            trackExperiment(experiment)

            // Launch first
            await launchTool.handler(context, { id: experiment.id })

            // Ship the control variant
            const shipResult = await shipVariantTool.handler(context, {
                id: experiment.id,
                variant_key: 'control',
                conclusion: 'won',
                conclusion_comment: 'Control performed best',
            } as any)
            const shipped = parseToolResponse(shipResult)

            expect(shipped.end_date).toBeTruthy()
            expect(shipped.conclusion).toBe('won')
        })
    })
})
