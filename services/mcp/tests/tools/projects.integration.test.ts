import { v4 as uuidv4 } from 'uuid'
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
import getProjectsTool from '@/tools/projects/getProjects'
import setActiveProjectTool from '@/tools/projects/setActive'
import updateEventDefinitionTool from '@/tools/projects/updateEventDefinition'
import updatePropertyDefinitionTool from '@/tools/projects/updatePropertyDefinition'
import type { Context } from '@/tools/types'

describe('Projects', { concurrent: false }, () => {
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

    describe.skip('get-projects tool', () => {
        const getTool = getProjectsTool()

        it('should list all projects for the active organization', async () => {
            const result = await getTool.handler(context, {})
            const projects = parseToolResponse(result)

            expect(Array.isArray(projects)).toBe(true)
            expect(projects.length).toBeGreaterThan(0)

            const project = projects[0]
            expect(project).toHaveProperty('id')
            expect(project).toHaveProperty('name')
        })

        it('should return projects with proper structure', async () => {
            const result = await getTool.handler(context, {})
            const projects = parseToolResponse(result)

            const testProject = projects.find((proj: any) => proj.id === Number(TEST_PROJECT_ID))
            expect(testProject).toBeTruthy()
            expect(testProject.id).toBe(Number(TEST_PROJECT_ID))
        })
    })

    describe('switch-project tool', () => {
        const setTool = setActiveProjectTool()

        it('should set active project and return context prompt', async () => {
            const targetProject = TEST_PROJECT_ID!
            const setResult = await setTool.handler(context, { projectId: Number(targetProject) })

            const text = setResult.content[0]!.text
            expect(text).toContain(`Switched to project ${targetProject}`)
            expect(text).toContain('Current context:')
        })
    })

    describe('event-definition-update tool', () => {
        const updateTool = updateEventDefinitionTool()

        it('should update event definition description', async () => {
            const testDescription = `Test description ${uuidv4()}`
            const result = await updateTool.handler(context, {
                eventName: '$pageview',
                data: { description: testDescription },
            })
            const eventDef = parseToolResponse(result)

            expect(eventDef.description).toBe(testDescription)
            expect(eventDef.name).toBe('$pageview')
            expect(eventDef.url).toContain('/data-management/events/')
        })

        it('should update event definition tags', async () => {
            const testTag = `test-tag-${uuidv4().slice(0, 8)}`
            const result = await updateTool.handler(context, {
                eventName: '$pageview',
                data: { tags: [testTag] },
            })
            const eventDef = parseToolResponse(result)

            expect(eventDef.tags).toContain(testTag)
        })

        it('should update verified status', async () => {
            const result = await updateTool.handler(context, {
                eventName: '$pageview',
                data: { verified: true },
            })
            const eventDef = parseToolResponse(result)

            expect(eventDef.verified).toBe(true)
        })

        it('should update multiple fields at once', async () => {
            const testDescription = `Multi-field test ${uuidv4()}`
            const testTag = `multi-tag-${uuidv4().slice(0, 8)}`
            const result = await updateTool.handler(context, {
                eventName: '$pageview',
                data: {
                    description: testDescription,
                    tags: [testTag],
                    verified: true,
                },
            })
            const eventDef = parseToolResponse(result)

            expect(eventDef.description).toBe(testDescription)
            expect(eventDef.tags).toContain(testTag)
            expect(eventDef.verified).toBe(true)
        })

        it('should throw error for non-existent event', async () => {
            const nonExistentEvent = `non-existent-event-${uuidv4()}`
            await expect(
                updateTool.handler(context, {
                    eventName: nonExistentEvent,
                    data: { description: 'test' },
                })
            ).rejects.toThrow()
        })
    })

    describe('property-definition-update tool', () => {
        const updateTool = updatePropertyDefinitionTool()

        beforeAll(async () => {
            // Ensure the $browser property definition exists before running update tests.
            // In a fresh test environment no events have been ingested, so property
            // definitions don't exist yet. We create one via the API if missing.
            const searchResult = await context.api.request<{ results: { name: string }[] }>({
                method: 'GET',
                path: `/api/projects/${TEST_PROJECT_ID}/property_definitions/`,
                query: { properties: '$browser', type: 'event' },
            })
            const exists = searchResult.results.some((def) => def.name === '$browser')
            if (!exists) {
                await context.api.request({
                    method: 'POST',
                    path: `/api/projects/${TEST_PROJECT_ID}/property_definitions/`,
                    body: { name: '$browser', type: 1, is_numerical: false },
                })
            }
        })

        it('should update property definition description', async () => {
            const testDescription = `Test description ${uuidv4()}`
            const result = await updateTool.handler(context, {
                propertyName: '$browser',
                type: 'event',
                data: { description: testDescription },
            })
            const propertyDef = parseToolResponse(result)

            expect(propertyDef.description).toBe(testDescription)
            expect(propertyDef.name).toBe('$browser')
            // The definition-detail route is keyed by id, not name, so the link must carry the id
            expect(propertyDef.url).toContain(`/data-management/properties/${propertyDef.id}`)
        })

        it('should update property definition tags', async () => {
            const testTag = `test-tag-${uuidv4().slice(0, 8)}`
            const result = await updateTool.handler(context, {
                propertyName: '$browser',
                type: 'event',
                data: { tags: [testTag] },
            })
            const propertyDef = parseToolResponse(result)

            expect(propertyDef.tags).toContain(testTag)
        })

        it('should update verified status', async () => {
            const result = await updateTool.handler(context, {
                propertyName: '$browser',
                type: 'event',
                data: { verified: true },
            })
            const propertyDef = parseToolResponse(result)

            expect(propertyDef.verified).toBe(true)
        })

        it('should update multiple fields at once', async () => {
            const testDescription = `Multi-field test ${uuidv4()}`
            const testTag = `multi-tag-${uuidv4().slice(0, 8)}`
            const result = await updateTool.handler(context, {
                propertyName: '$browser',
                type: 'event',
                data: {
                    description: testDescription,
                    tags: [testTag],
                    verified: true,
                },
            })
            const propertyDef = parseToolResponse(result)

            expect(propertyDef.description).toBe(testDescription)
            expect(propertyDef.tags).toContain(testTag)
            expect(propertyDef.verified).toBe(true)
        })

        it('should throw error for non-existent property', async () => {
            const nonExistentProperty = `non-existent-property-${uuidv4()}`
            await expect(
                updateTool.handler(context, {
                    propertyName: nonExistentProperty,
                    type: 'event',
                    data: { description: 'test' },
                })
            ).rejects.toThrow()
        })
    })

    describe('Projects workflow', () => {
        it.skip('should support listing and setting active project workflow', async () => {
            const getTool = getProjectsTool()
            const setTool = setActiveProjectTool()

            const projectsResult = await getTool.handler(context, {})
            const projects = parseToolResponse(projectsResult)
            expect(projects.length).toBeGreaterThan(0)

            const targetProject = projects.find((p: any) => p.id === Number(TEST_PROJECT_ID)) || projects[0]

            const setResult = await setTool.handler(context, { projectId: targetProject.id })
            expect(setResult.content[0]!.text).toContain(`Switched to project ${targetProject.id}`)

            await context.cache.set('projectId', targetProject.id.toString())
        })
    })
})
