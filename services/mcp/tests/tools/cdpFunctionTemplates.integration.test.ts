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
import { GENERATED_TOOLS } from '@/tools/generated/cdp_function_templates'
import type { Context } from '@/tools/types'

describe('Hog Function Templates', { concurrent: false }, () => {
    let context: Context

    const listTool = GENERATED_TOOLS['cdp-function-templates-list']!()
    const retrieveTool = GENERATED_TOOLS['cdp-function-templates-retrieve']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    describe('cdp-function-templates-list tool', () => {
        it('should return paginated structure with results', async () => {
            const result = await listTool.handler(context, {})
            const data = parseToolResponse(result)

            expect(typeof data.count).toBe('number')
            expect(Array.isArray(data.results)).toBe(true)
            expect(typeof data._posthogUrl).toBe('string')
            expect(data._posthogUrl).toContain('/pipeline/templates')
        })

        it('should return templates with required fields', async () => {
            const result = await listTool.handler(context, { limit: 5 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)

            if (data.results.length > 0) {
                const template = data.results[0]
                expect(template).toHaveProperty('id')
                expect(template).toHaveProperty('name')
                expect(template).toHaveProperty('type')
                expect(typeof template.name).toBe('string')
            }
        })

        it('should respect the limit parameter', async () => {
            const result = await listTool.handler(context, { limit: 1 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(1)
        })

        it('should filter by template_id', async () => {
            const allResult = await listTool.handler(context, { limit: 1 })
            const { results: allResults } = parseToolResponse(allResult)

            if (allResults.length === 0) {
                return
            }

            const knownId: string = allResults[0].id

            const result = await listTool.handler(context, { template_id: knownId })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBe(1)
            expect(data.results[0].id).toBe(knownId)
        })

        it('should respect the offset parameter', async () => {
            // Fetch two consecutive pages in a single logical test to verify offset works.
            // Templates are sorted by popularity which can shift between calls, so we
            // only check structural pagination properties rather than exact ID ordering.
            const firstPage = parseToolResponse(await listTool.handler(context, { limit: 2, offset: 0 }))
            const secondPage = parseToolResponse(await listTool.handler(context, { limit: 2, offset: 2 }))

            expect(firstPage.results.length).toBe(2)
            expect(secondPage.results.length).toBeGreaterThan(0)

            // The two pages should not share any IDs
            const firstIds = new Set(firstPage.results.map((t: any) => t.id))
            for (const t of secondPage.results) {
                expect(firstIds.has(t.id)).toBe(false)
            }
        })
    })

    describe('cdp-function-templates-retrieve tool', () => {
        it('should retrieve a template by template_id', async () => {
            const listResult = await listTool.handler(context, { limit: 1 })
            const { results } = parseToolResponse(listResult)

            if (results.length === 0) {
                // No templates available in this environment — nothing to fetch.
                return
            }

            const templateId: string = results[0].id

            const result = await retrieveTool.handler(context, { template_id: templateId })
            const tpl = parseToolResponse(result)

            expect(tpl.id).toBe(templateId)
            expect(typeof tpl.name).toBe('string')
            expect(typeof tpl.type).toBe('string')
        })

        it('should return full template details including code and inputs_schema', async () => {
            const listResult = await listTool.handler(context, { limit: 1 })
            const { results } = parseToolResponse(listResult)

            if (results.length === 0) {
                return
            }

            const result = await retrieveTool.handler(context, { template_id: results[0].id })
            const tpl = parseToolResponse(result)

            // Templates have source code and may have inputs_schema
            expect(tpl.code == null || typeof tpl.code === 'string').toBe(true)
            expect(tpl.inputs_schema == null || Array.isArray(tpl.inputs_schema)).toBe(true)
        })

        it('should throw for a non-existent template_id', async () => {
            await expect(
                retrieveTool.handler(context, { template_id: 'template-this-does-not-exist-xyz' })
            ).rejects.toThrow()
        })
    })

    describe('Hog Function Templates workflow', () => {
        it('should support a list → retrieve workflow', async () => {
            const listResult = await listTool.handler(context, { limit: 5 })
            const { results, count } = parseToolResponse(listResult)

            expect(typeof count).toBe('number')
            expect(Array.isArray(results)).toBe(true)

            if (results.length === 0) {
                return
            }

            // Retrieve each of the first page items
            for (const item of results) {
                const retrieveResult = await retrieveTool.handler(context, { template_id: item.id })
                const tpl = parseToolResponse(retrieveResult)

                expect(tpl.id).toBe(item.id)
                expect(tpl.name).toBe(item.name)
            }
        })
    })
})
