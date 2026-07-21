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
import { GENERATED_TOOLS } from '@/tools/generated/billing_alerts'
import type { Context } from '@/tools/types'

describe('Billing alerts', { concurrent: false }, () => {
    let context: Context
    const createdAlertIds: string[] = []

    const createTool = GENERATED_TOOLS['billing-alert-create']!()
    const updateTool = GENERATED_TOOLS['billing-alert-update']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        for (const id of createdAlertIds) {
            try {
                await context.api.request({
                    method: 'DELETE',
                    path: `/api/organizations/${encodeURIComponent(TEST_ORG_ID!)}/billing/alerts/${encodeURIComponent(id)}/`,
                })
            } catch {
                // Best effort. The alert may already have been removed.
            }
        }
        createdAlertIds.length = 0
    })

    it('creates and partially updates an organization billing alert', async () => {
        const name = `MCP billing alert ${generateUniqueKey('billing')}`
        const createResult = await createTool.handler(context, {
            name,
            enabled: false,
            threshold_type: 'absolute_value',
            threshold_value: '100.000000',
        })
        const created = parseToolResponse(createResult)
        createdAlertIds.push(created.id)

        expect(created.name).toBe(name)
        expect(created.threshold_type).toBe('absolute_value')
        expect(created.threshold_value).toBe('100.000000')
        expect(created.configuration_revision).toBe(1)

        const updatedName = `${name} updated`
        const updateResult = await updateTool.handler(context, {
            id: created.id,
            name: updatedName,
            threshold_value: '125.000000',
        })
        const updated = parseToolResponse(updateResult)

        expect(updated.id).toBe(created.id)
        expect(updated.name).toBe(updatedName)
        expect(updated.threshold_value).toBe('125.000000')
        expect(updated.configuration_revision).toBe(2)
    })
})
