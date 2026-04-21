import { beforeAll, describe, expect, it } from 'vitest'

import {
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/integrations'
import type { Context } from '@/tools/types'

describe('Integrations', { concurrent: false }, () => {
    let context: Context

    const listTool = GENERATED_TOOLS['integrations-list']!()
    const getTool = GENERATED_TOOLS['integration-get']!()
    const deleteTool = GENERATED_TOOLS['integration-delete']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    // Integration creation requires OAuth flows, file uploads, or sensitive credentials,
    // so we cannot do full CRUD lifecycle tests. Tests focus on read operations and
    // error handling for non-existent resources.

    describe('integrations-list tool', () => {
        it('should return a paginated list response', async () => {
            const result = await listTool.handler(context, {})
            const data = parseToolResponse(result)

            expect(typeof data.count).toBe('number')
            expect(Array.isArray(data.results)).toBe(true)
            expect(typeof data._posthogUrl).toBe('string')
        })

        it('should respect the limit parameter', async () => {
            const result = await listTool.handler(context, { limit: 1 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(1)
        })
    })

    describe('integration-get tool', () => {
        it('should throw for a non-existent ID', async () => {
            await expect(getTool.handler(context, { id: 999999 })).rejects.toThrow()
        })

        it('should retrieve an integration from the list if any exist', async () => {
            const listResult = await listTool.handler(context, { limit: 1 })
            const listData = parseToolResponse(listResult)

            if (listData.results.length === 0) {
                return // no integrations to test with
            }

            const integration = listData.results[0]
            const getResult = await getTool.handler(context, { id: integration.id })
            const data = parseToolResponse(getResult)

            expect(data.id).toBe(integration.id)
            expect(typeof data.kind).toBe('string')
        })
    })

    describe('integration-delete tool', () => {
        it('should throw for a non-existent ID', async () => {
            await expect(deleteTool.handler(context, { id: 999999 })).rejects.toThrow()
        })
    })
})
