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
import { GENERATED_TOOLS } from '@/tools/generated/endpoints'
import type { Context } from '@/tools/types'

const HOGQL_PAGEVIEW_QUERY = {
    kind: 'HogQLQuery',
    query: "SELECT event FROM events WHERE event = '$pageview' LIMIT 10",
}

const HOGQL_EVENT_COUNT_QUERY = {
    kind: 'HogQLQuery',
    query: 'SELECT event, count() AS cnt FROM events GROUP BY event ORDER BY cnt DESC LIMIT 10',
}

function endpointName(label: string): string {
    return `ep-${generateUniqueKey(label)}`
}

describe('Endpoints', { concurrent: false }, () => {
    let context: Context
    const createdEndpointNames: string[] = []

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        for (const name of createdEndpointNames) {
            try {
                await context.api.request({
                    method: 'PATCH',
                    path: `/api/projects/${TEST_PROJECT_ID}/endpoints/${name}/`,
                    body: { deleted: true },
                })
            } catch (error) {
                console.warn(`Failed to cleanup endpoint ${name}:`, error)
            }
        }
        createdEndpointNames.length = 0
    })

    describe('endpoint-create tool', () => {
        const createTool = GENERATED_TOOLS['endpoint-create']!()

        it('should create an endpoint with a HogQL query', async () => {
            const name = endpointName('create')
            const result = await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
            })
            const endpoint = parseToolResponse(result)

            expect(endpoint.name).toBe(name)
            expect(endpoint._posthogUrl).toContain(`/endpoints/${name}`)

            createdEndpointNames.push(name)
        })

        it('should create an endpoint with description and data_freshness_seconds', async () => {
            const name = endpointName('opts')
            const result = await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
                description: 'Integration test endpoint',
                data_freshness_seconds: 3600,
            })
            const endpoint = parseToolResponse(result)

            expect(endpoint.name).toBe(name)
            expect(endpoint.description).toBe('Integration test endpoint')
            expect(endpoint.data_freshness_seconds).toBe(3600)

            createdEndpointNames.push(name)
        })

        it('should create an endpoint with materialization disabled', async () => {
            const name = endpointName('nomat')
            const result = await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
                is_materialized: false,
            })
            const endpoint = parseToolResponse(result)

            expect(endpoint.name).toBe(name)
            expect(endpoint.is_materialized).toBe(false)

            createdEndpointNames.push(name)
        })
    })

    describe('endpoints-get-all tool', () => {
        const getAllTool = GENERATED_TOOLS['endpoints-get-all']!()
        const createTool = GENERATED_TOOLS['endpoint-create']!()

        it('should list endpoints including a freshly created one', async () => {
            const name = endpointName('list')
            const createResult = await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
            })
            parseToolResponse(createResult)
            createdEndpointNames.push(name)

            const result = await getAllTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.some((e: { name: string }) => e.name === name)).toBe(true)
        })

        it('should support pagination', async () => {
            const result = await getAllTool.handler(context, { limit: 1, offset: 0 })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeLessThanOrEqual(1)
        })
    })

    describe('endpoint-get tool', () => {
        const getTool = GENERATED_TOOLS['endpoint-get']!()
        const createTool = GENERATED_TOOLS['endpoint-create']!()

        it('should get a specific endpoint by name', async () => {
            const name = endpointName('get')
            const createResult = await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
                description: 'Get test endpoint',
            })
            parseToolResponse(createResult)
            createdEndpointNames.push(name)

            const result = await getTool.handler(context, { name })
            const endpoint = parseToolResponse(result)

            expect(endpoint.name).toBe(name)
            expect(endpoint.description).toBe('Get test endpoint')
            expect(endpoint._posthogUrl).toContain(`/endpoints/${name}`)
        })
    })

    describe('endpoint-update tool', () => {
        const updateTool = GENERATED_TOOLS['endpoint-update']!()
        const createTool = GENERATED_TOOLS['endpoint-create']!()

        it('should update description and data_freshness_seconds', async () => {
            const name = endpointName('update')
            await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
            })
            createdEndpointNames.push(name)

            const result = await updateTool.handler(context, {
                name,
                description: 'Updated description',
                data_freshness_seconds: 21600,
            })
            const updated = parseToolResponse(result)

            expect(updated.name).toBe(name)
            expect(updated.description).toBe('Updated description')
            expect(updated.data_freshness_seconds).toBe(21600)
        })

        it('should deactivate an endpoint', async () => {
            const name = endpointName('deactivate')
            await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
            })
            createdEndpointNames.push(name)

            const result = await updateTool.handler(context, {
                name,
                is_active: false,
            })
            const updated = parseToolResponse(result)

            expect(updated.name).toBe(name)
            expect(updated.is_active).toBe(false)
        })
    })

    describe('endpoint-delete tool', () => {
        const deleteTool = GENERATED_TOOLS['endpoint-delete']!()
        const createTool = GENERATED_TOOLS['endpoint-create']!()
        const getAllTool = GENERATED_TOOLS['endpoints-get-all']!()

        it('should delete an endpoint', async () => {
            const name = endpointName('delete')
            await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
            })
            // Don't add to createdEndpointNames since we're deleting it

            await deleteTool.handler(context, { name })

            const listResult = await getAllTool.handler(context, {})
            const response = parseToolResponse(listResult)
            expect(response.results.some((e: { name: string }) => e.name === name)).toBe(false)
        })
    })

    describe('endpoint-run tool', () => {
        const runTool = GENERATED_TOOLS['endpoint-run']!()
        const createTool = GENERATED_TOOLS['endpoint-create']!()

        it('should execute an endpoint and return results', async () => {
            const name = endpointName('run')
            await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
            })
            createdEndpointNames.push(name)

            const result = await runTool.handler(context, { name })
            const response = parseToolResponse(result)

            expect(response.name).toBe(name)
            expect(Array.isArray(response.columns)).toBe(true)
            expect(Array.isArray(response.results)).toBe(true)
        })
    })

    describe('endpoint-versions tool', () => {
        const versionsTool = GENERATED_TOOLS['endpoint-versions']!()
        const createTool = GENERATED_TOOLS['endpoint-create']!()

        it('should list versions for an endpoint', async () => {
            const name = endpointName('versions')
            await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
            })
            createdEndpointNames.push(name)

            const result = await versionsTool.handler(context, { name })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeGreaterThanOrEqual(1)
            expect(response.results[0].version).toBe(1)
        })
    })

    describe('endpoint-materialization-status tool', () => {
        const matStatusTool = GENERATED_TOOLS['endpoint-materialization-status']!()
        const createTool = GENERATED_TOOLS['endpoint-create']!()

        it('should return materialization status', async () => {
            const name = endpointName('matstatus')
            await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
            })
            createdEndpointNames.push(name)

            const result = await matStatusTool.handler(context, { name })
            const status = parseToolResponse(result)

            expect(status.name).toBe(name)
            expect(typeof status.can_materialize).toBe('boolean')
        })
    })

    describe('endpoint-openapi-spec tool', () => {
        const openapiSpecTool = GENERATED_TOOLS['endpoint-openapi-spec']!()
        const createTool = GENERATED_TOOLS['endpoint-create']!()
        const updateTool = GENERATED_TOOLS['endpoint-update']!()

        it('should return an OpenAPI 3.0 spec for an endpoint', async () => {
            const name = endpointName('openapi')
            await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
                description: 'OpenAPI spec test endpoint',
            })
            createdEndpointNames.push(name)

            const result = await openapiSpecTool.handler(context, { name })
            const spec = parseToolResponse(result)

            expect(spec.openapi).toBe('3.0.3')
            expect(spec.info.title).toBe(name)
            expect(spec.info.description).toBe('OpenAPI spec test endpoint')
            expect(spec.paths).toBeTruthy()

            const runPath = Object.keys(spec.paths)[0]!
            expect(runPath).toContain(`/endpoints/${name}/run`)
            expect(spec.paths[runPath].post).toBeTruthy()
            expect(spec.components.securitySchemes.PersonalAPIKey).toBeTruthy()
        })

        it('should return the spec for a specific version', async () => {
            const name = endpointName('openapi-ver')
            await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
                description: 'Version 1',
            })
            createdEndpointNames.push(name)

            // Update query to create version 2
            await updateTool.handler(context, {
                name,
                query: HOGQL_EVENT_COUNT_QUERY,
                description: 'Version 2',
            })

            // Fetch spec for version 1
            const v1Result = await openapiSpecTool.handler(context, { name, version: 1 })
            const v1Spec = parseToolResponse(v1Result)
            expect(v1Spec.info.version).toBe('1')
            expect(v1Spec.info.description).toBe('Version 1')

            // Fetch spec for version 2
            const v2Result = await openapiSpecTool.handler(context, { name, version: 2 })
            const v2Spec = parseToolResponse(v2Result)
            expect(v2Spec.info.version).toBe('2')
            expect(v2Spec.info.description).toBe('Version 2')
        })
    })

    describe('Lifecycle workflows', () => {
        const createTool = GENERATED_TOOLS['endpoint-create']!()
        const getTool = GENERATED_TOOLS['endpoint-get']!()
        const getAllTool = GENERATED_TOOLS['endpoints-get-all']!()
        const updateTool = GENERATED_TOOLS['endpoint-update']!()
        const runTool = GENERATED_TOOLS['endpoint-run']!()
        const versionsTool = GENERATED_TOOLS['endpoint-versions']!()
        const deleteTool = GENERATED_TOOLS['endpoint-delete']!()

        it('should complete a full CRUD lifecycle', async () => {
            const name = endpointName('lifecycle')

            // Create
            const createResult = await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
                description: 'Lifecycle test',
            })
            const created = parseToolResponse(createResult)
            expect(created.name).toBe(name)

            // Get
            const getResult = await getTool.handler(context, { name })
            const fetched = parseToolResponse(getResult)
            expect(fetched.name).toBe(name)
            expect(fetched.description).toBe('Lifecycle test')

            // List
            const listResult = await getAllTool.handler(context, {})
            const listed = parseToolResponse(listResult)
            expect(listed.results.some((e: { name: string }) => e.name === name)).toBe(true)

            // Update
            const updateResult = await updateTool.handler(context, {
                name,
                description: 'Updated lifecycle test',
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.description).toBe('Updated lifecycle test')

            // Run
            const runResult = await runTool.handler(context, { name })
            const ran = parseToolResponse(runResult)
            expect(ran.name).toBe(name)
            expect(Array.isArray(ran.columns)).toBe(true)

            // Versions
            const versionsResult = await versionsTool.handler(context, { name })
            const versions = parseToolResponse(versionsResult)
            expect(versions.results.length).toBeGreaterThanOrEqual(1)

            // Delete
            await deleteTool.handler(context, { name })
            const afterDeleteList = await getAllTool.handler(context, {})
            const afterDelete = parseToolResponse(afterDeleteList)
            expect(afterDelete.results.some((e: { name: string }) => e.name === name)).toBe(false)
        })

        it('should auto-create a new version when query changes', async () => {
            const name = endpointName('autoversion')
            const createResult = await createTool.handler(context, {
                name,
                query: HOGQL_PAGEVIEW_QUERY,
            })
            const created = parseToolResponse(createResult)
            expect(created.current_version).toBe(1)
            createdEndpointNames.push(name)

            // Update with a different query — should bump version
            const updateResult = await updateTool.handler(context, {
                name,
                query: HOGQL_EVENT_COUNT_QUERY,
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.current_version).toBe(2)

            // Verify two versions exist
            const versionsResult = await versionsTool.handler(context, { name })
            const versions = parseToolResponse(versionsResult)
            expect(versions.results.length).toBe(2)
        })
    })
})
