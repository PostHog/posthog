import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import readDataWarehouseSchemaTool from '@/tools/posthogAiTools/readDataWarehouseSchema'
import type { Context } from '@/tools/types'

describe('Data schema tools', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
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

    describe('read-data-warehouse-schema tool', () => {
        const tool = readDataWarehouseSchemaTool()

        it('should return core PostHog table schema text', async () => {
            const result = await tool.handler(context, {})

            expect(typeof result).toBe('string')
            expect(result).toContain('# Core PostHog tables')
            expect(result).toContain('## Table `events`')
            expect(result).toContain('## Table `persons`')
        })
    })
})
