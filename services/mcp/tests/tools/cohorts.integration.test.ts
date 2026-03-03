import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/cohorts'
import type { Context } from '@/tools/types'

describe('Cohorts', { concurrent: false }, () => {
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

    describe('cohorts-list tool', () => {
        const listTool = GENERATED_TOOLS['cohorts-list']!()
        const createTool = GENERATED_TOOLS['cohorts-create']!()

        it('should list cohorts including a newly created one', async () => {
            const name = `List Test ${generateUniqueKey('list')}`
            const createResult = await createTool.handler(context, {
                name,
                is_static: true,
            })
            const created = parseToolResponse(createResult)
            createdResources.cohorts.push(created.id)

            const result = await listTool.handler(context, {})
            const cohorts = parseToolResponse(result)

            expect(Array.isArray(cohorts)).toBe(true)
            const found = cohorts.find((c: { id: number }) => c.id === created.id)
            expect(found).toBeTruthy()
            expect(found.name).toBe(name)
            expect(found.url).toContain('/cohorts/')
        })

        it('should support pagination', async () => {
            const result = await listTool.handler(context, { limit: 5, offset: 0 })
            const cohorts = parseToolResponse(result)

            expect(Array.isArray(cohorts)).toBe(true)
            expect(cohorts.length).toBeLessThanOrEqual(5)
        })
    })

    describe('cohorts-create tool', () => {
        const createTool = GENERATED_TOOLS['cohorts-create']!()

        it('should create a dynamic cohort with filters', async () => {
            const name = `Dynamic Cohort ${generateUniqueKey('dynamic')}`
            const result = await createTool.handler(context, {
                name,
                description: 'Integration test dynamic cohort',
                filters: {
                    properties: {
                        type: 'OR',
                        values: [
                            {
                                type: 'person',
                                key: '$browser',
                                value: 'Chrome',
                                operator: 'exact',
                            },
                        ],
                    },
                },
            })
            const cohort = parseToolResponse(result)

            expect(cohort.id).toBeTruthy()
            expect(cohort.name).toBe(name)
            expect(cohort.description).toBe('Integration test dynamic cohort')
            expect(cohort.url).toContain('/cohorts/')

            createdResources.cohorts.push(cohort.id)
        })

        it('should create a static cohort', async () => {
            const name = `Static Cohort ${generateUniqueKey('static')}`
            const result = await createTool.handler(context, {
                name,
                is_static: true,
            })
            const cohort = parseToolResponse(result)

            expect(cohort.id).toBeTruthy()
            expect(cohort.name).toBe(name)
            expect(cohort.is_static).toBe(true)
            expect(cohort.url).toContain('/cohorts/')

            createdResources.cohorts.push(cohort.id)
        })
    })

    describe('cohorts-retrieve tool', () => {
        const createTool = GENERATED_TOOLS['cohorts-create']!()
        const retrieveTool = GENERATED_TOOLS['cohorts-retrieve']!()

        it('should retrieve a specific cohort by ID', async () => {
            const name = `Retrieve Test ${generateUniqueKey('retrieve')}`
            const createResult = await createTool.handler(context, {
                name,
                description: 'For retrieve test',
                is_static: true,
            })
            const created = parseToolResponse(createResult)
            createdResources.cohorts.push(created.id)

            const result = await retrieveTool.handler(context, { id: created.id })
            const cohort = parseToolResponse(result)

            expect(cohort.id).toBe(created.id)
            expect(cohort.name).toBe(name)
            expect(cohort.description).toBe('For retrieve test')
            expect(cohort.url).toContain('/cohorts/')
        })
    })

    describe('cohorts-partial-update tool', () => {
        const createTool = GENERATED_TOOLS['cohorts-create']!()
        const updateTool = GENERATED_TOOLS['cohorts-partial-update']!()

        it('should update cohort name and description', async () => {
            const createResult = await createTool.handler(context, {
                name: `Original ${generateUniqueKey('orig')}`,
                is_static: true,
            })
            const created = parseToolResponse(createResult)
            createdResources.cohorts.push(created.id)

            const updatedName = `Updated ${generateUniqueKey('upd')}`
            const result = await updateTool.handler(context, {
                id: created.id,
                name: updatedName,
                description: 'Updated description',
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.name).toBe(updatedName)
            expect(updated.description).toBe('Updated description')
        })

        it('should soft-delete a cohort', async () => {
            const createResult = await createTool.handler(context, {
                name: `Delete Test ${generateUniqueKey('delete')}`,
                is_static: true,
            })
            const created = parseToolResponse(createResult)

            const result = await updateTool.handler(context, {
                id: created.id,
                deleted: true,
            })
            const deleted = parseToolResponse(result)

            expect(deleted.id).toBe(created.id)

            const listTool = GENERATED_TOOLS['cohorts-list']!()
            const listResult = await listTool.handler(context, {})
            const cohorts = parseToolResponse(listResult)
            expect(cohorts.some((c: { id: number }) => c.id === created.id)).toBe(false)
        })
    })

    describe('static cohort person management', () => {
        const createTool = GENERATED_TOOLS['cohorts-create']!()
        const addPersonsTool = GENERATED_TOOLS['cohorts-add-persons-to-static-cohort-partial-update']!()
        const removePersonTool = GENERATED_TOOLS['cohorts-remove-person-from-static-cohort-partial-update']!()

        it('should reject adding persons to a dynamic cohort', async () => {
            const createResult = await createTool.handler(context, {
                name: `Dynamic Reject Test ${generateUniqueKey('dyn-reject')}`,
                filters: {
                    properties: {
                        type: 'OR',
                        values: [{ type: 'person', key: '$browser', value: 'Chrome', operator: 'exact' }],
                    },
                },
            })
            const created = parseToolResponse(createResult)
            createdResources.cohorts.push(created.id)

            const fakeUuid = '00000000-0000-4000-8000-000000000003'
            await expect(
                addPersonsTool.handler(context, {
                    id: created.id,
                    person_ids: [fakeUuid],
                })
            ).rejects.toThrow()
        })

        it('should reject non-existent person UUIDs', async () => {
            const createResult = await createTool.handler(context, {
                name: `Add Persons Test ${generateUniqueKey('add')}`,
                is_static: true,
            })
            const created = parseToolResponse(createResult)
            createdResources.cohorts.push(created.id)

            const fakeUuid = '00000000-0000-4000-8000-000000000001'
            await expect(
                addPersonsTool.handler(context, {
                    id: created.id,
                    person_ids: [fakeUuid],
                })
            ).rejects.toThrow('Validation error')
        })

        it('should reject removing a person UUID that does not exist in the team', async () => {
            const createResult = await createTool.handler(context, {
                name: `Remove Person Test ${generateUniqueKey('remove')}`,
                is_static: true,
            })
            const created = parseToolResponse(createResult)
            createdResources.cohorts.push(created.id)

            const fakeUuid = '00000000-0000-4000-8000-000000000002'
            await expect(
                removePersonTool.handler(context, {
                    id: created.id,
                    person_id: fakeUuid,
                })
            ).rejects.toThrow()
        })
    })

    describe('cohort workflow', () => {
        it('should support create, list, retrieve, update workflow', async () => {
            const createTool = GENERATED_TOOLS['cohorts-create']!()
            const listTool = GENERATED_TOOLS['cohorts-list']!()
            const retrieveTool = GENERATED_TOOLS['cohorts-retrieve']!()
            const updateTool = GENERATED_TOOLS['cohorts-partial-update']!()

            const name = `Workflow Test ${generateUniqueKey('workflow')}`
            const createResult = await createTool.handler(context, {
                name,
                is_static: true,
            })
            const created = parseToolResponse(createResult)
            createdResources.cohorts.push(created.id)

            const listResult = await listTool.handler(context, {})
            const cohorts = parseToolResponse(listResult)
            expect(cohorts.some((c: { id: number }) => c.id === created.id)).toBe(true)

            const retrieveResult = await retrieveTool.handler(context, { id: created.id })
            const retrieved = parseToolResponse(retrieveResult)
            expect(retrieved.name).toBe(name)

            const updatedName = `Updated Workflow ${generateUniqueKey('upd-wf')}`
            const updateResult = await updateTool.handler(context, {
                id: created.id,
                name: updatedName,
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.name).toBe(updatedName)
        })
    })
})
