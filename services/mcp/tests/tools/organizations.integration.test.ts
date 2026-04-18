import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import setActiveOrganizationTool from '@/tools/organizations/setActive'
import type { Context } from '@/tools/types'

describe('Organizations', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
        cohorts: [],
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

    describe('organizations-list tool', () => {
        const getTool = GENERATED_TOOL_MAP['organizations-list']!()

        it('should list all organizations', async () => {
            const result = await getTool.handler(context, {})
            const parsed = parseToolResponse(result)
            const orgs = parsed.results

            expect(Array.isArray(orgs)).toBe(true)
            expect(orgs.length).toBeGreaterThan(0)

            const org = orgs[0]
            expect(org).toHaveProperty('id')
            expect(org).toHaveProperty('name')
            expect(org).toHaveProperty('slug')
        })

        it('should return organizations with filtered fields only', async () => {
            const result = await getTool.handler(context, {})
            const parsed = parseToolResponse(result)

            const testOrg = parsed.results.find((org: any) => org.id === TEST_ORG_ID)
            expect(testOrg).toBeTruthy()
            expect(testOrg.id).toBe(TEST_ORG_ID)
            // Verify response filtering — verbose fields should be excluded
            expect(testOrg).not.toHaveProperty('teams')
            expect(testOrg).not.toHaveProperty('projects')
            expect(testOrg).not.toHaveProperty('available_product_features')
        })
    })

    describe('set-active-organization tool', () => {
        const setTool = setActiveOrganizationTool()

        it('should set active organization', async () => {
            const getTool = GENERATED_TOOL_MAP['organizations-list']!()
            const orgsResult = await getTool.handler(context, {})
            const parsed = parseToolResponse(orgsResult)
            const orgs = parsed.results
            expect(orgs.length).toBeGreaterThan(0)

            const targetOrg = orgs[0]
            const setResult = await setTool.handler(context, { orgId: targetOrg.id })

            expect(setResult.content[0]!.text).toBe(`Switched to organization ${targetOrg.id}`)
        })

        it('should handle invalid organization ID', async () => {
            try {
                await setTool.handler(context, { orgId: 'invalid-org-id-12345' })
                expect.fail('Should have thrown an error')
            } catch (error) {
                expect(error).toBeTruthy()
            }
        })
    })

    describe('organization-get tool', () => {
        const getDetailsTool = GENERATED_TOOL_MAP['organization-get']!()

        it('should get organization details by ID', async () => {
            const result = await getDetailsTool.handler(context, { id: TEST_ORG_ID })
            const orgDetails = parseToolResponse(result)

            expect(orgDetails.id).toBe(TEST_ORG_ID)
            expect(orgDetails).toHaveProperty('name')
            expect(orgDetails).toHaveProperty('member_count')
        })

        it('should fall back to active organization when id is omitted', async () => {
            // Ensure the active org is set (earlier tests may have corrupted the cache)
            await context.cache.set('orgId', TEST_ORG_ID)
            const result = await getDetailsTool.handler(context, {})
            const orgDetails = parseToolResponse(result)

            expect(orgDetails.id).toBe(TEST_ORG_ID)
            expect(orgDetails).toHaveProperty('name')
            expect(orgDetails).toHaveProperty('member_count')
        })

        it('should include lean projects and teams', async () => {
            const result = await getDetailsTool.handler(context, { id: TEST_ORG_ID })
            const orgDetails = parseToolResponse(result)

            expect(orgDetails.projects).toBeTruthy()
            expect(Array.isArray(orgDetails.projects)).toBe(true)

            if (orgDetails.projects.length > 0) {
                const project = orgDetails.projects[0]
                expect(project).toHaveProperty('id')
                expect(project).toHaveProperty('name')
                // Verify only lean fields are present
                expect(Object.keys(project).sort()).toEqual(['id', 'name'].sort())
            }

            if (orgDetails.teams?.length > 0) {
                const team = orgDetails.teams[0]
                expect(team).toHaveProperty('id')
                expect(team).toHaveProperty('name')
                // Should not have verbose fields
                expect(team).not.toHaveProperty('api_token')
                expect(team).not.toHaveProperty('uuid')
            }
        })
    })

    describe('Organization workflow', () => {
        it('should support listing and setting active org workflow', async () => {
            const getTool = GENERATED_TOOL_MAP['organizations-list']!()
            const setTool = setActiveOrganizationTool()

            const orgsResult = await getTool.handler(context, {})
            const parsed = parseToolResponse(orgsResult)
            const orgs = parsed.results
            expect(orgs.length).toBeGreaterThan(0)

            const targetOrg = orgs.find((org: any) => org.id === TEST_ORG_ID) || orgs[0]

            const setResult = await setTool.handler(context, { orgId: targetOrg.id })
            expect(setResult.content[0]!.text).toBe(`Switched to organization ${targetOrg.id}`)

            await context.cache.set('orgId', targetOrg.id)
        })
    })
})
