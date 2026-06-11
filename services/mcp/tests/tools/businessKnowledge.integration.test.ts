import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import {
    API_BASE_URL,
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
import type { Context } from '@/tools/types'

describe('Business knowledge sources', { concurrent: false }, () => {
    let context: Context
    const createdSourceIds: string[] = []

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
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

        it('should create a URL source with source_type dispatched correctly', async () => {
            const name = generateUniqueKey('MCP URL Source')
            const result = await urlCreateTool.handler(context, {
                name,
                url: `${API_BASE_URL}/robots.txt`,
            })
            const source = parseToolResponse(result)

            expect(source.id).toBeTruthy()
            expect(source.name).toBe(name)
            expect(source.source_type).toBe('url')
            createdSourceIds.push(source.id)
        })

        it('should accept refresh_interval', async () => {
            const name = generateUniqueKey('MCP URL Refresh')
            const result = await urlCreateTool.handler(context, {
                name,
                url: `${API_BASE_URL}/robots.txt`,
                refresh_interval: '24h',
            })
            const source = parseToolResponse(result)

            expect(source.id).toBeTruthy()
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
