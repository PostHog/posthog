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
import getOrganizationDetailsTool from '@/tools/organizations/getDetails'
import getOrganizationsTool from '@/tools/organizations/getOrganizations'
import setActiveOrganizationTool from '@/tools/organizations/setActive'
import type { Context } from '@/tools/types'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

describe.skip('Organizations', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
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

    describe('get-organizations tool', () => {
        const getTool = getOrganizationsTool()

        it('should list all organizations', async () => {
            const result = await getTool.handler(context, {})
            const orgs = parseToolResponse(result)

            expect(Array.isArray(orgs)).toBe(true)
            expect(orgs.length).toBeGreaterThan(0)

            const org = orgs[0]
            expect(org).toHaveProperty('id')
            expect(org).toHaveProperty('name')
        })

        it('should return organizations with proper structure', async () => {
            const result = await getTool.handler(context, {})
            const orgs = parseToolResponse(result)

            const testOrg = orgs.find((org: any) => org.id === TEST_ORG_ID)
            expect(testOrg).toBeDefined()
            expect(testOrg.id).toBe(TEST_ORG_ID)
        })
    })

    describe('set-active-organization tool', () => {
        const setTool = setActiveOrganizationTool()
        const getTool = getOrganizationsTool()

        it('should set active organization', async () => {
            const orgsResult = await getTool.handler(context, {})
            const orgs = parseToolResponse(orgsResult)
            expect(orgs.length).toBeGreaterThan(0)

            const targetOrg = orgs[0]
            const setResult = await setTool.handler(context, { orgId: targetOrg.id })

            expect(setResult.content[0].text).toBe(`Switched to organization ${targetOrg.id}`)
        })

        it('should handle invalid organization ID', async () => {
            try {
                await setTool.handler(context, { orgId: 'invalid-org-id-12345' })
                expect.fail('Should have thrown an error')
            } catch (error) {
                expect(error).toBeDefined()
            }
        })
    })

    describe('get-organization-details tool', () => {
        const getDetailsTool = getOrganizationDetailsTool()

        it.skip('should get organization details for active org', async () => {
            const result = await getDetailsTool.handler(context, {})
            const orgDetails = parseToolResponse(result)

            expect(orgDetails.id).toBe(TEST_ORG_ID)
            expect(orgDetails).toHaveProperty('name')
            expect(orgDetails).toHaveProperty('projects')
            expect(Array.isArray(orgDetails.projects)).toBe(true)
        })

        it.skip('should include projects in organization details', async () => {
            const result = await getDetailsTool.handler(context, {})
            const orgDetails = parseToolResponse(result)

            expect(orgDetails.projects).toBeDefined()
            expect(Array.isArray(orgDetails.projects)).toBe(true)

            if (orgDetails.projects.length > 0) {
                const project = orgDetails.projects[0]
                expect(project).toHaveProperty('id')
                expect(project).toHaveProperty('name')
            }

            const testProject = orgDetails.projects.find(
                (p: any) => p.id === Number(TEST_PROJECT_ID)
            )
            expect(testProject).toBeDefined()
        })
    })

    describe('Organization workflow', () => {
        it('should support listing and setting active org workflow', async () => {
            const getTool = getOrganizationsTool()
            const setTool = setActiveOrganizationTool()

            const orgsResult = await getTool.handler(context, {})
            const orgs = parseToolResponse(orgsResult)
            expect(orgs.length).toBeGreaterThan(0)

            const targetOrg = orgs.find((org: any) => org.id === TEST_ORG_ID) || orgs[0]

            const setResult = await setTool.handler(context, { orgId: targetOrg.id })
            expect(setResult.content[0].text).toBe(`Switched to organization ${targetOrg.id}`)

            await context.cache.set('orgId', targetOrg.id)
        })
    })
})
