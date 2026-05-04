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
import { GENERATED_TOOLS } from '@/tools/generated/persons'
import type { Context } from '@/tools/types'

describe('Persons', { concurrent: false }, () => {
    let context: Context

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    describe('persons-list tool', () => {
        const listTool = GENERATED_TOOLS['persons-list']!()

        it('should list persons with paginated results', async () => {
            const result = await listTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(response.results).toBeTruthy()
            expect(Array.isArray(response.results)).toBe(true)
            expect(response._posthogUrl).toContain('/persons')

            if (response.results.length > 0) {
                const person = response.results[0]
                expect(Object.keys(person).sort()).toEqual(
                    ['created_at', 'distinct_ids', 'id', 'last_seen_at', 'name', 'properties', 'uuid'].sort()
                )
            }
        })

        it('should support pagination with limit and offset', async () => {
            const result = await listTool.handler(context, { limit: 2, offset: 0 })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeLessThanOrEqual(2)
        })

        it('should support search by email', async () => {
            // Find a person with an email property to use as a search term
            const allResult = await listTool.handler(context, { limit: 100 })
            const allResponse = parseToolResponse(allResult)
            const personWithEmail = allResponse.results.find((p: any) => p.properties?.email || p.properties?.$email)

            if (!personWithEmail) {
                console.warn('No persons with email found in project, skipping search by email test')
                return
            }

            const email = personWithEmail.properties.email ?? personWithEmail.properties.$email
            const result = await listTool.handler(context, { search: email })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeGreaterThan(0)

            // Verify only the dot-notation picked properties are present (no full properties blob leaked)
            const allowedProps = new Set(['email', '$email', '$geoip_country_code'])
            const person = response.results[0]
            for (const key of Object.keys(person.properties)) {
                expect(allowedProps).toContain(key)
            }
        })
    })

    describe('persons-retrieve tool', () => {
        const listTool = GENERATED_TOOLS['persons-list']!()
        const retrieveTool = GENERATED_TOOLS['persons-retrieve']!()

        it('should retrieve a person by ID', async () => {
            const listResult = await listTool.handler(context, { limit: 1 })
            const listResponse = parseToolResponse(listResult)

            if (listResponse.results.length === 0) {
                console.warn('No persons found in project, skipping retrieve test')
                return
            }

            const person = listResponse.results[0]
            const result = await retrieveTool.handler(context, { id: person.id })
            const retrieved = parseToolResponse(result)

            expect(retrieved.uuid).toBe(person.uuid)
            expect(retrieved.distinct_ids).toBeTruthy()
            expect(retrieved.properties).toBeTruthy()
            expect(retrieved._posthogUrl).toContain('/persons/')
        })
    })

    describe('persons-values-retrieve tool', () => {
        const valuesTool = GENERATED_TOOLS['persons-values-retrieve']!()

        it('should return values for a person property key', async () => {
            const result = await valuesTool.handler(context, { key: 'email' })
            const response = parseToolResponse(result)

            expect(response.results).toBeTruthy()
            expect(Array.isArray(response.results)).toBe(true)
        })

        it('should filter values by search string', async () => {
            const result = await valuesTool.handler(context, { key: 'email', value: 'test' })
            const response = parseToolResponse(result)

            expect(response.results).toBeTruthy()
            expect(Array.isArray(response.results)).toBe(true)
        })
    })

    describe('persons-cohorts-retrieve tool', () => {
        const listTool = GENERATED_TOOLS['persons-list']!()
        const cohortsTool = GENERATED_TOOLS['persons-cohorts-retrieve']!()

        it('should return cohorts for a person', async () => {
            const listResult = await listTool.handler(context, { limit: 1 })
            const listResponse = parseToolResponse(listResult)

            if (listResponse.results.length === 0) {
                console.warn('No persons found in project, skipping cohorts test')
                return
            }

            const person = listResponse.results[0]
            const result = await cohortsTool.handler(context, { person_id: String(person.uuid) })
            const response = parseToolResponse(result)
            expect(response.results).toBeTruthy()
            expect(Array.isArray(response.results)).toBe(true)
        })
    })

    describe('persons-property-set tool', () => {
        const listTool = GENERATED_TOOLS['persons-list']!()
        const updatePropertyTool = GENERATED_TOOLS['persons-property-set']!()

        it('should set a property on a person', async () => {
            const listResult = await listTool.handler(context, { limit: 1 })
            const listResponse = parseToolResponse(listResult)

            if (listResponse.results.length === 0) {
                console.warn('No persons found in project, skipping update property test')
                return
            }

            const person = listResponse.results[0]
            const testKey = `mcp_test_prop_${Date.now()}`

            // The endpoint returns 202 Accepted with no body
            const result = await updatePropertyTool.handler(context, {
                id: person.id,
                key: testKey,
                value: 'test_value',
            })
            expect(result).toBeTruthy()
        })
    })

    describe('persons-property-delete tool', () => {
        const listTool = GENERATED_TOOLS['persons-list']!()
        const deletePropertyTool = GENERATED_TOOLS['persons-property-delete']!()

        it('should delete a property from a person', async () => {
            const listResult = await listTool.handler(context, { limit: 1 })
            const listResponse = parseToolResponse(listResult)

            if (listResponse.results.length === 0) {
                console.warn('No persons found in project, skipping delete property test')
                return
            }

            const person = listResponse.results[0]

            // The endpoint uses capture_internal to send an event, which may fail
            // in dev/CI environments where the ingestion pipeline isn't running
            try {
                const result = await deletePropertyTool.handler(context, {
                    id: person.id,
                    unset: 'mcp_test_prop_nonexistent',
                })
                expect(result).toBeTruthy()
            } catch (error: any) {
                expect(error.message).toMatch(/Unable to delete property|500/)
            }
        })
    })

    describe('persons workflow', () => {
        it('should support list, retrieve, get values, and get cohorts', async () => {
            const listTool = GENERATED_TOOLS['persons-list']!()
            const retrieveTool = GENERATED_TOOLS['persons-retrieve']!()
            const valuesTool = GENERATED_TOOLS['persons-values-retrieve']!()
            const cohortsTool = GENERATED_TOOLS['persons-cohorts-retrieve']!()

            // List persons
            const listResult = await listTool.handler(context, { limit: 5 })
            const listResponse = parseToolResponse(listResult)
            expect(Array.isArray(listResponse.results)).toBe(true)

            if (listResponse.results.length === 0) {
                console.warn('No persons found in project, skipping workflow test')
                return
            }

            // Retrieve a specific person
            const person = listResponse.results[0]
            const retrieveResult = await retrieveTool.handler(context, { id: person.id })
            const retrieved = parseToolResponse(retrieveResult)
            expect(retrieved.uuid).toBe(person.uuid)
            expect(retrieved.distinct_ids).toBeTruthy()

            // Get property values
            const valuesResult = await valuesTool.handler(context, { key: 'email' })
            const valuesResponse = parseToolResponse(valuesResult)
            expect(Array.isArray(valuesResponse.results)).toBe(true)

            // Get cohorts for the person
            const cohortsResult = await cohortsTool.handler(context, { person_id: String(person.uuid) })
            const cohortsResponse = parseToolResponse(cohortsResult)
            expect(cohortsResponse.results).toBeTruthy()
            expect(Array.isArray(cohortsResponse.results)).toBe(true)
        })
    })
})
