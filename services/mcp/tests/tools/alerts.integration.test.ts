import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    SAMPLE_TREND_QUERIES,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/alerts'
import type { Context } from '@/tools/types'

describe('Alerts', { concurrent: false }, () => {
    let context: Context
    let insightId: number
    let currentUserId: number
    const createdAlertIds: string[] = []

    const listTool = GENERATED_TOOLS['alerts-list']!()
    const getTool = GENERATED_TOOLS['alert-get']!()
    const createTool = GENERATED_TOOLS['alert-create']!()
    const updateTool = GENERATED_TOOLS['alert-update']!()
    const deleteTool = GENERATED_TOOLS['alert-delete']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)

        // Create a trends insight as a prerequisite — alerts require an insight to monitor
        const insight = await context.api.request<{ id: number }>({
            method: 'POST',
            path: `/api/projects/${TEST_PROJECT_ID}/insights/`,
            body: {
                name: generateUniqueKey('alert-test-insight'),
                query: SAMPLE_TREND_QUERIES.basicPageviews,
            },
        })
        insightId = insight.id

        // Fetch the current user ID — required for subscribed_users
        const user = await context.api.request<{ id: number }>({
            method: 'GET',
            path: '/api/users/@me/',
        })
        currentUserId = user.id
    })

    afterEach(async () => {
        for (const id of createdAlertIds) {
            try {
                await deleteTool.handler(context, { id })
            } catch {
                // best effort — alert may already be deleted
            }
        }
        createdAlertIds.length = 0
    })

    function makeAlertParams(overrides: Record<string, unknown> = {}): Record<string, unknown> {
        return {
            name: `test-alert-${generateUniqueKey('alert')}`,
            insight: insightId,
            subscribed_users: [currentUserId],
            threshold: {
                configuration: {
                    type: 'absolute' as const,
                    bounds: { upper: 100 },
                },
            },
            condition: {
                type: 'absolute_value' as const,
            },
            config: {
                type: 'TrendsAlertConfig' as const,
                series_index: 0,
            },
            enabled: false,
            ...overrides,
        }
    }

    describe('alerts-list tool', () => {
        it('should return paginated structure', async () => {
            const result = await listTool.handler(context, {})
            const data = parseToolResponse(result)

            expect(typeof data.count).toBe('number')
            expect(Array.isArray(data.results)).toBe(true)
            expect(typeof data._posthogUrl).toBe('string')
            expect(data._posthogUrl).toContain('/insights')
        })

        it('should respect the limit parameter', async () => {
            const result = await listTool.handler(context, { limit: 1 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(1)
        })
    })

    describe('alert-create tool', () => {
        it('should create an alert with absolute threshold', async () => {
            const params = makeAlertParams()
            const result = await createTool.handler(context, params)
            const alert = parseToolResponse(result)
            createdAlertIds.push(alert.id)

            expect(alert.id).toBeTruthy()
            expect(alert.name).toBe(params.name)
            expect(alert.enabled).toBe(false)
            expect(alert.threshold.configuration.type).toBe('absolute')
            expect(alert.threshold.configuration.bounds.upper).toBe(100)
        })

        it('should create an alert with relative_increase condition', async () => {
            const params = makeAlertParams({
                condition: { type: 'relative_increase' },
                threshold: {
                    configuration: {
                        type: 'percentage',
                        bounds: { upper: 50 },
                    },
                },
            })
            const result = await createTool.handler(context, params)
            const alert = parseToolResponse(result)
            createdAlertIds.push(alert.id)

            expect(alert.id).toBeTruthy()
            expect(alert.condition.type).toBe('relative_increase')
            expect(alert.threshold.configuration.type).toBe('percentage')
        })

        it('should create an alert with calculation_interval', async () => {
            const params = makeAlertParams({ calculation_interval: 'weekly' })
            const result = await createTool.handler(context, params)
            const alert = parseToolResponse(result)
            createdAlertIds.push(alert.id)

            expect(alert.calculation_interval).toBe('weekly')
        })
    })

    describe('alert-get tool', () => {
        it('should retrieve a specific alert by ID', async () => {
            const created = await createTool.handler(context, makeAlertParams())
            const createdAlert = parseToolResponse(created)
            createdAlertIds.push(createdAlert.id)

            const result = await getTool.handler(context, { id: createdAlert.id })
            const alert = parseToolResponse(result)

            expect(alert.id).toBe(createdAlert.id)
            expect(alert.name).toBe(createdAlert.name)
            expect(alert.threshold).toBeTruthy()
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(getTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('alert-update tool', () => {
        it('should update the name of an alert', async () => {
            const created = await createTool.handler(context, makeAlertParams())
            const alert = parseToolResponse(created)
            createdAlertIds.push(alert.id)

            const newName = `renamed-${generateUniqueKey('alert')}`
            const result = await updateTool.handler(context, { id: alert.id, name: newName })
            const updated = parseToolResponse(result)

            expect(updated.name).toBe(newName)
            expect(updated.id).toBe(alert.id)
        })

        it('should enable and disable an alert', async () => {
            const created = await createTool.handler(context, makeAlertParams({ enabled: false }))
            const alert = parseToolResponse(created)
            createdAlertIds.push(alert.id)

            const enableResult = await updateTool.handler(context, { id: alert.id, enabled: true })
            const enabled = parseToolResponse(enableResult)
            expect(enabled.enabled).toBe(true)

            const disableResult = await updateTool.handler(context, { id: alert.id, enabled: false })
            const disabled = parseToolResponse(disableResult)
            expect(disabled.enabled).toBe(false)
        })

        it('should update threshold bounds', async () => {
            const created = await createTool.handler(context, makeAlertParams())
            const alert = parseToolResponse(created)
            createdAlertIds.push(alert.id)

            const result = await updateTool.handler(context, {
                id: alert.id,
                threshold: {
                    configuration: {
                        type: 'absolute' as const,
                        bounds: { lower: 10, upper: 200 },
                    },
                },
            })
            const updated = parseToolResponse(result)

            expect(updated.threshold.configuration.bounds.lower).toBe(10)
            expect(updated.threshold.configuration.bounds.upper).toBe(200)
        })

        it('should update calculation_interval', async () => {
            const created = await createTool.handler(context, makeAlertParams())
            const alert = parseToolResponse(created)
            createdAlertIds.push(alert.id)

            const result = await updateTool.handler(context, { id: alert.id, calculation_interval: 'hourly' })
            const updated = parseToolResponse(result)

            expect(updated.calculation_interval).toBe('hourly')
        })
    })

    describe('alert-delete tool', () => {
        it('should delete an alert', async () => {
            const created = await createTool.handler(context, makeAlertParams())
            const alert = parseToolResponse(created)

            await deleteTool.handler(context, { id: alert.id })
            await expect(getTool.handler(context, { id: alert.id })).rejects.toThrow()
        })
    })

    describe('anomaly detection alerts', () => {
        const simulateTool = GENERATED_TOOLS['alert-simulate']!()

        it('should create an alert with detector_config', async () => {
            const params = makeAlertParams({
                detector_config: {
                    type: 'zscore',
                    threshold: 0.9,
                    window: 30,
                },
            })
            const result = await createTool.handler(context, params)
            const alert = parseToolResponse(result)
            createdAlertIds.push(alert.id)

            expect(alert.id).toBeTruthy()
            expect(alert.detector_config).toBeTruthy()
            expect(alert.detector_config.type).toBe('zscore')
            expect(alert.detector_config.threshold).toBe(0.9)
            expect(alert.detector_config.window).toBe(30)
        })

        it('should create an ensemble alert with multiple detectors', async () => {
            const params = makeAlertParams({
                detector_config: {
                    type: 'ensemble',
                    operator: 'or',
                    detectors: [
                        { type: 'zscore', threshold: 0.9, window: 30 },
                        { type: 'mad', threshold: 0.9, window: 30 },
                    ],
                },
            })
            const result = await createTool.handler(context, params)
            const alert = parseToolResponse(result)
            createdAlertIds.push(alert.id)

            expect(alert.detector_config.type).toBe('ensemble')
            expect(alert.detector_config.operator).toBe('or')
            expect(alert.detector_config.detectors).toHaveLength(2)
        })

        it('should update an alert to add detector_config', async () => {
            const created = await createTool.handler(context, makeAlertParams())
            const alert = parseToolResponse(created)
            createdAlertIds.push(alert.id)

            expect(alert.detector_config).toBeNull()

            const result = await updateTool.handler(context, {
                id: alert.id,
                detector_config: {
                    type: 'mad',
                    threshold: 0.95,
                    window: 60,
                },
            })
            const updated = parseToolResponse(result)

            expect(updated.detector_config).toBeTruthy()
            expect(updated.detector_config.type).toBe('mad')
        })

        it('should simulate a detector on an insight', async () => {
            const result = await simulateTool.handler(context, {
                insight: insightId,
                detector_config: {
                    type: 'zscore',
                    threshold: 0.9,
                    window: 30,
                },
                series_index: 0,
            })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.data)).toBe(true)
            expect(Array.isArray(data.dates)).toBe(true)
            expect(Array.isArray(data.scores)).toBe(true)
            expect(Array.isArray(data.triggered_indices)).toBe(true)
            expect(Array.isArray(data.triggered_dates)).toBe(true)
            expect(typeof data.total_points).toBe('number')
            expect(typeof data.anomaly_count).toBe('number')
            expect(data.total_points).toBeGreaterThan(0)
            expect(data.scores.length).toBe(data.total_points)
        })

        it('should simulate with a custom date range', async () => {
            const result = await simulateTool.handler(context, {
                insight: insightId,
                detector_config: {
                    type: 'zscore',
                    threshold: 0.9,
                    window: 30,
                },
                date_from: '-7d',
            })
            const data = parseToolResponse(result)

            expect(data.total_points).toBeGreaterThan(0)
        })
    })

    describe('Alerts workflow', () => {
        it('should support a full create → retrieve → update → delete lifecycle', async () => {
            const name = `workflow-alert-${generateUniqueKey('lifecycle')}`

            // Create
            const createResult = await createTool.handler(context, makeAlertParams({ name }))
            const created = parseToolResponse(createResult)
            expect(created.id).toBeTruthy()
            expect(created.name).toBe(name)

            // Retrieve
            const getResult = await getTool.handler(context, { id: created.id })
            const retrieved = parseToolResponse(getResult)
            expect(retrieved.id).toBe(created.id)

            // Update
            const updatedName = `${name}-updated`
            const updateResult = await updateTool.handler(context, {
                id: created.id,
                name: updatedName,
                enabled: true,
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.name).toBe(updatedName)
            expect(updated.enabled).toBe(true)

            // Delete
            await deleteTool.handler(context, { id: created.id })
            await expect(getTool.handler(context, { id: created.id })).rejects.toThrow()
        })

        it('should appear in list results after creation', async () => {
            const name = `list-check-alert-${generateUniqueKey('appear')}`

            const createResult = await createTool.handler(context, makeAlertParams({ name }))
            const created = parseToolResponse(createResult)
            createdAlertIds.push(created.id)

            const listResult = await listTool.handler(context, {})
            const data = parseToolResponse(listResult)

            const found = data.results.find((a: any) => a.id === created.id)
            expect(found).toBeTruthy()
            expect(found.name).toBe(name)
        })
    })
})
