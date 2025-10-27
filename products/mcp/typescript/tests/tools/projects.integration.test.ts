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
import eventDefinitionsTool from '@/tools/projects/eventDefinitions'
import getProjectsTool from '@/tools/projects/getProjects'
import propertyDefinitionsTool from '@/tools/projects/propertyDefinitions'
import setActiveProjectTool from '@/tools/projects/setActive'
import type { Context } from '@/tools/types'
import { v4 as uuidv4 } from 'uuid'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

describe('Projects', { concurrent: false }, () => {
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
            expect(testProject).toBeDefined()
            expect(testProject.id).toBe(Number(TEST_PROJECT_ID))
        })
    })

    describe('switch-project tool', () => {
        const setTool = setActiveProjectTool()

        it('should set active project', async () => {
            const targetProject = TEST_PROJECT_ID!
            const setResult = await setTool.handler(context, { projectId: Number(targetProject) })

            expect(setResult.content[0].text).toBe(`Switched to project ${targetProject}`)
        })
    })

    describe('properties-list tool', () => {
        const propertyDefsTool = propertyDefinitionsTool()

        it('should get property definitions for a specific event', async () => {
            const result = await propertyDefsTool.handler(context, {
                type: 'event',
                eventName: '$pageview',
            })
            const propertyDefs = parseToolResponse(result)

            expect(Array.isArray(propertyDefs)).toBe(true)
        })

        it('should return property definitions with proper structure', async () => {
            const result = await propertyDefsTool.handler(context, {
                type: 'event',
                eventName: '$pageview',
            })
            const propertyDefs = parseToolResponse(result)

            if (propertyDefs.length > 0) {
                const prop = propertyDefs[0]
                expect(prop).toHaveProperty('name')
                expect(prop).toHaveProperty('property_type')
                expect(typeof prop.name).toBe('string')
                // property_type can be a string or null
                expect(['string', 'object', 'undefined'].includes(typeof prop.property_type)).toBe(
                    true
                )
            }
        })

        it('should handle invalid event names gracefully', async () => {
            try {
                const result = await propertyDefsTool.handler(context, {
                    type: 'event',
                    eventName: `non-existent-event-${uuidv4()}`,
                })
                const propertyDefs = parseToolResponse(result)
                expect(Array.isArray(propertyDefs)).toBe(true)
            } catch (error) {
                expect(error).toBeInstanceOf(Error)
            }
        })

        it('should get property definitions for persons', async () => {
            const result = await propertyDefsTool.handler(context, {
                type: 'person',
            })
            const propertyDefs = parseToolResponse(result)
            expect(Array.isArray(propertyDefs)).toBe(true)
            expect(propertyDefs.length).toBeGreaterThan(0)
        })
    })

    describe('event-definitions-list tool', () => {
        const eventDefsTool = eventDefinitionsTool()

        it('should list all event definitions for active project', async () => {
            const result = await eventDefsTool.handler(context, {})
            const eventDefs = parseToolResponse(result)

            expect(Array.isArray(eventDefs)).toBe(true)
        })

        it('should return event definitions with proper structure', async () => {
            const result = await eventDefsTool.handler(context, {})
            const eventDefs = parseToolResponse(result)

            if (eventDefs.length > 0) {
                const eventDef = eventDefs[0]
                expect(eventDef).toHaveProperty('name')
                expect(eventDef).toHaveProperty('last_seen_at')
                expect(typeof eventDef.name).toBe('string')
            }
        })

        it('should include common events like $pageview', async () => {
            const result = await eventDefsTool.handler(context, {})
            const eventDefs = parseToolResponse(result)

            const pageviewEvent = eventDefs.find((event: any) => event.name === '$pageview')
            if (eventDefs.length > 0) {
                expect(pageviewEvent).toBeDefined()
            }
        })

        it('should filter event definitions with search parameter', async () => {
            const result = await eventDefsTool.handler(context, { q: 'pageview' })
            const eventDefs = parseToolResponse(result)

            expect(Array.isArray(eventDefs)).toBe(true)

            // All returned events should contain "pageview" in their name
            for (const event of eventDefs) {
                expect(event.name.toLowerCase()).toContain('pageview')
            }
        })

        it('should return empty array when searching for non-existent events', async () => {
            const result = await eventDefsTool.handler(context, { q: 'non-existent-event-xyz123' })
            const eventDefs = parseToolResponse(result)

            expect(Array.isArray(eventDefs)).toBe(true)
            expect(eventDefs.length).toBe(0)
        })

        it('should return all events when no search parameter is provided', async () => {
            const resultWithoutSearch = await eventDefsTool.handler(context, {})
            const resultWithSearch = await eventDefsTool.handler(context, { q: 'pageview' })

            const allEventDefs = parseToolResponse(resultWithoutSearch)
            const filteredEventDefs = parseToolResponse(resultWithSearch)

            expect(Array.isArray(allEventDefs)).toBe(true)
            expect(Array.isArray(filteredEventDefs)).toBe(true)

            if (allEventDefs.length > 0 && filteredEventDefs.length > 0) {
                // Filtered results should be a subset of all results
                expect(filteredEventDefs.length).toBeLessThanOrEqual(allEventDefs.length)
            }
        })
    })

    describe('Projects workflow', () => {
        it.skip('should support listing and setting active project workflow', async () => {
            const getTool = getProjectsTool()
            const setTool = setActiveProjectTool()

            const projectsResult = await getTool.handler(context, {})
            const projects = parseToolResponse(projectsResult)
            expect(projects.length).toBeGreaterThan(0)

            const targetProject =
                projects.find((p: any) => p.id === Number(TEST_PROJECT_ID)) || projects[0]

            const setResult = await setTool.handler(context, { projectId: targetProject.id })
            expect(setResult.content[0].text).toBe(`Switched to project ${targetProject.id}`)

            await context.cache.set('projectId', targetProject.id.toString())
        })
    })
})
