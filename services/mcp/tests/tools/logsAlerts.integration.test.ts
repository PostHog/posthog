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
import { GENERATED_TOOLS as FF_TOOLS } from '@/tools/generated/feature_flags'
import { GENERATED_TOOLS } from '@/tools/generated/logs'
import type { Context } from '@/tools/types'

describe('Logs Alerts', { concurrent: false }, () => {
    let context: Context
    const createdAlertIds: string[] = []

    const createTool = GENERATED_TOOLS['logs-alerts-create']!()
    const listTool = GENERATED_TOOLS['logs-alerts-list']!()
    const retrieveTool = GENERATED_TOOLS['logs-alerts-retrieve']!()
    const updateTool = GENERATED_TOOLS['logs-alerts-partial-update']!()
    const deleteTool = GENERATED_TOOLS['logs-alerts-destroy']!()

    function makeAlertParams(overrides: Record<string, unknown> = {}): Record<string, unknown> {
        return {
            name: `Test alert ${generateUniqueKey('alert')}`,
            filters: { severityLevels: ['error', 'fatal'] },
            threshold_count: 10,
            threshold_operator: 'above' as const,
            window_minutes: 5,
            ...overrides,
        }
    }

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)

        // Ensure the logs-alerting feature flag is active — the API is gated behind it
        const listFlags = FF_TOOLS['feature-flag-get-all']!()
        const updateFlag = FF_TOOLS['update-feature-flag']!()
        const createFlag = FF_TOOLS['create-feature-flag']!()

        const flagsResult = await listFlags.handler(context, { search: 'logs-alerting' })
        const flags = (flagsResult as any).results ?? []
        const flag = flags.find((f: any) => f.key === 'logs-alerting')
        // eslint-disable-next-line no-console -- Intentionally preserved for debugging feature flag state in integration test
        console.log('flag', flag)

        if (flag && !flag.active) {
            const updateResult = await updateFlag.handler(context, { id: flag.id, active: true })
            // eslint-disable-next-line no-console -- Preserve output for test visibility
            console.log('updateResult', updateResult)
        } else if (!flag) {
            const createResult = await createFlag.handler(context, {
                key: 'logs-alerting',
                name: 'Logs alerting',
                active: true,
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100 }],
                },
            })
            // eslint-disable-next-line no-console -- Preserve output for test visibility
            console.log('createResult', createResult)
        }
    })

    afterEach(async () => {
        for (const id of createdAlertIds) {
            try {
                await deleteTool.handler(context, { id })
            } catch {
                // best effort
            }
        }
        createdAlertIds.length = 0
    })

    describe('logs-alerts-create', () => {
        it('should create an alert with required fields', async () => {
            const params = makeAlertParams()

            const result = await createTool.handler(context, params)
            const alert = parseToolResponse(result)

            expect(alert.id).toBeTruthy()
            expect(alert.name).toBe(params.name)
            expect(alert.threshold_count).toBe(10)
            expect(alert.threshold_operator).toBe('above')
            expect(alert.window_minutes).toBe(5)
            expect(alert.state).toBe('not_firing')
            expect(alert.enabled).toBe(true)

            createdAlertIds.push(alert.id)
        })

        it('should create an alert with custom configuration', async () => {
            const params = makeAlertParams({
                enabled: false,
                threshold_operator: 'below',
                window_minutes: 60,
                evaluation_periods: 3,
                datapoints_to_alarm: 2,
                cooldown_minutes: 15,
            })

            const result = await createTool.handler(context, params)
            const alert = parseToolResponse(result)

            expect(alert.enabled).toBe(false)
            expect(alert.threshold_operator).toBe('below')
            expect(alert.window_minutes).toBe(60)
            expect(alert.evaluation_periods).toBe(3)
            expect(alert.datapoints_to_alarm).toBe(2)
            expect(alert.cooldown_minutes).toBe(15)

            createdAlertIds.push(alert.id)
        })
    })

    describe('logs-alerts-list', () => {
        it('should list alerts including a newly created one', async () => {
            const createResult = await createTool.handler(context, makeAlertParams())
            const created = parseToolResponse(createResult)
            createdAlertIds.push(created.id)

            const result = await listTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(response).toHaveProperty('count')
            expect(Array.isArray(response.results)).toBe(true)
            expect(response).toHaveProperty('_posthogUrl')
            expect(response.results.some((a: { id: string }) => a.id === created.id)).toBe(true)
        })

        it('should support pagination', async () => {
            const result = await listTool.handler(context, { limit: 5, offset: 0 })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeLessThanOrEqual(5)
        })
    })

    describe('logs-alerts-retrieve', () => {
        it('should retrieve an alert by ID', async () => {
            const params = makeAlertParams()
            const createResult = await createTool.handler(context, params)
            const created = parseToolResponse(createResult)
            createdAlertIds.push(created.id)

            const result = await retrieveTool.handler(context, { id: created.id })
            const alert = parseToolResponse(result)

            expect(alert.id).toBe(created.id)
            expect(alert.name).toBe(params.name)
            expect(alert.threshold_count).toBe(10)
        })

        it('should throw for non-existent ID', async () => {
            await expect(retrieveTool.handler(context, { id: crypto.randomUUID() })).rejects.toThrow()
        })
    })

    describe('logs-alerts-partial-update', () => {
        it('should update alert name', async () => {
            const createResult = await createTool.handler(context, makeAlertParams())
            const created = parseToolResponse(createResult)
            createdAlertIds.push(created.id)

            const updatedName = `Updated ${generateUniqueKey('upd')}`
            const result = await updateTool.handler(context, {
                id: created.id,
                name: updatedName,
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.name).toBe(updatedName)
        })

        it('should update threshold configuration', async () => {
            const createResult = await createTool.handler(context, makeAlertParams())
            const created = parseToolResponse(createResult)
            createdAlertIds.push(created.id)

            const result = await updateTool.handler(context, {
                id: created.id,
                threshold_count: 50,
                threshold_operator: 'below',
                window_minutes: 30,
            })
            const updated = parseToolResponse(result)

            expect(updated.threshold_count).toBe(50)
            expect(updated.threshold_operator).toBe('below')
            expect(updated.window_minutes).toBe(30)
        })

        it('should update enabled state', async () => {
            const createResult = await createTool.handler(context, makeAlertParams())
            const created = parseToolResponse(createResult)
            createdAlertIds.push(created.id)

            const result = await updateTool.handler(context, {
                id: created.id,
                enabled: false,
            })
            const updated = parseToolResponse(result)

            expect(updated.enabled).toBe(false)
        })
    })

    describe('logs-alerts-destroy', () => {
        it('should delete an alert', async () => {
            const createResult = await createTool.handler(context, makeAlertParams())
            const created = parseToolResponse(createResult)

            await deleteTool.handler(context, { id: created.id })

            await expect(retrieveTool.handler(context, { id: created.id })).rejects.toThrow()
        })
    })

    describe('full lifecycle', () => {
        it('should support create → retrieve → update → verify → delete', async () => {
            // Create
            const params = makeAlertParams()
            const createResult = await createTool.handler(context, params)
            const created = parseToolResponse(createResult)
            expect(created.id).toBeTruthy()
            expect(created.name).toBe(params.name)

            // Retrieve
            const retrieveResult = await retrieveTool.handler(context, { id: created.id })
            const retrieved = parseToolResponse(retrieveResult)
            expect(retrieved.id).toBe(created.id)
            expect(retrieved.name).toBe(params.name)

            // Update
            const updatedName = `Lifecycle updated ${generateUniqueKey('lc')}`
            const updateResult = await updateTool.handler(context, {
                id: created.id,
                name: updatedName,
                threshold_count: 25,
                enabled: false,
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.name).toBe(updatedName)
            expect(updated.threshold_count).toBe(25)
            expect(updated.enabled).toBe(false)

            // Verify via retrieve
            const verifyResult = await retrieveTool.handler(context, { id: created.id })
            const verified = parseToolResponse(verifyResult)
            expect(verified.name).toBe(updatedName)
            expect(verified.threshold_count).toBe(25)

            // Verify in list
            const listResult = await listTool.handler(context, {})
            const listData = parseToolResponse(listResult)
            expect(listData.results.some((a: { id: string }) => a.id === created.id)).toBe(true)

            // Delete
            await deleteTool.handler(context, { id: created.id })

            // Verify deletion
            await expect(retrieveTool.handler(context, { id: created.id })).rejects.toThrow()
        })
    })
})
