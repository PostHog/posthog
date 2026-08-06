import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import {
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    getToolByName,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS as FF_TOOLS } from '@/tools/generated/feature_flags'
import type { Context } from '@/tools/types'

const BK_FEATURE_FLAG = 'product-business-knowledge'

describe('Business knowledge sources', { concurrent: false }, () => {
    let context: Context
    const createdSourceIds: string[] = []

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)

        // The BK API is gated behind the product-business-knowledge flag — ensure it's active.
        const listFlags = FF_TOOLS['feature-flag-get-all']!()
        const updateFlag = FF_TOOLS['update-feature-flag']!()
        const createFlag = FF_TOOLS['create-feature-flag']!()

        const flagsResult = await listFlags.handler(context, { search: BK_FEATURE_FLAG })
        const flags = (flagsResult as any).results ?? []
        const flag = flags.find((f: any) => f.key === BK_FEATURE_FLAG)

        if (flag && !flag.active) {
            await updateFlag.handler(context, { id: flag.id, active: true })
        } else if (!flag) {
            await createFlag.handler(context, {
                key: BK_FEATURE_FLAG,
                name: 'Business knowledge',
                active: true,
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100 }],
                },
            })
        }
    })

    afterAll(async () => {
        for (const id of createdSourceIds) {
            try {
                await context.api.request({
                    method: 'DELETE',
                    path: `/api/projects/${TEST_PROJECT_ID}/business_knowledge/sources/${id}/`,
                })
            } catch (error) {
                console.warn(`Failed to cleanup knowledge source ${id}:`, error)
            }
        }
    })

    describe('text-create and retrieve', () => {
        const textCreateTool = getToolByName('business-knowledge-sources-text-create')
        const retrieveTool = getToolByName('business-knowledge-sources-retrieve')

        it('should create a text source and retrieve it by ID', async () => {
            const name = generateUniqueKey('MCP Text Source')
            const result = await textCreateTool.handler(context, {
                name,
                text: 'PostHog is an open-source product analytics platform.',
            })
            const source = parseToolResponse(result)

            expect(source.id).toBeTruthy()
            expect(source.name).toBe(name)
            expect(source.source_type).toBe('text')
            createdSourceIds.push(source.id)

            const retrieved = parseToolResponse(await retrieveTool.handler(context, { id: source.id }))
            expect(retrieved.id).toBe(source.id)
            expect(retrieved.name).toBe(name)
            expect(retrieved.source_type).toBe('text')
            expect(retrieved).not.toHaveProperty('_posthogUrl')
        })
    })

    describe('url-create', () => {
        const urlCreateTool = getToolByName('business-knowledge-sources-url-create')

        // Must be a public host: claim_url_source runs the SSRF check (is_url_allowed),
        // which blocks localhost/private hosts. The actual fetch is backgrounded and not
        // awaited here, so the URL only needs to pass SSRF, not return real content.
        const PUBLIC_TEST_URL = 'https://example.com/'

        // A URL source is claimed in PROCESSING and ingested in the background; the
        // backend enforces a single PROCESSING source per team, so a second concurrent
        // create would 409. We therefore exercise dispatch + refresh_interval in one
        // create rather than two.
        it('should dispatch source_type=url and persist refresh_interval', async () => {
            const name = generateUniqueKey('MCP URL Source')
            const result = await urlCreateTool.handler(context, {
                name,
                url: PUBLIC_TEST_URL,
                refresh_interval: '24h',
            })
            const source = parseToolResponse(result)

            expect(source.id).toBeTruthy()
            expect(source.name).toBe(name)
            expect(source.source_type).toBe('url')
            expect(source.refresh_interval).toBe('24h')
            createdSourceIds.push(source.id)
        })
    })

    describe('list', () => {
        const listTool = getToolByName('business-knowledge-sources-list')

        it('should return sources with filtered response fields', async () => {
            const result = await listTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(response.results).toBeTruthy()
            expect(Array.isArray(response.results)).toBe(true)
            expect(response).toHaveProperty('_posthogUrl')
            expect(response._posthogUrl).toContain('/business-knowledge')

            if (response.results.length > 0) {
                const source = response.results[0]
                expect(source).toHaveProperty('id')
                expect(source).toHaveProperty('name')
                expect(source).toHaveProperty('source_type')
                expect(source).toHaveProperty('status')

                const unexpectedFields = ['documents', 'source_text', 'team']
                for (const field of unexpectedFields) {
                    expect(source).not.toHaveProperty(field)
                }
            }
        })
    })
})
