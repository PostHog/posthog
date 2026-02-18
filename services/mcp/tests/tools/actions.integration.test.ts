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
import createActionTool from '@/tools/actions/create'
import deleteActionTool from '@/tools/actions/delete'
import getActionTool from '@/tools/actions/get'
import getAllActionsTool from '@/tools/actions/getAll'
import updateActionTool from '@/tools/actions/update'
import type { Context } from '@/tools/types'

describe('Actions', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
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

    describe('action-create tool', () => {
        const createTool = createActionTool()

        it('should create an action with event-based step', async () => {
            const params = {
                name: `Test Action ${generateUniqueKey('action')}`,
                description: 'Integration test action',
                steps: [
                    {
                        event: '$pageview',
                        url: '/signup',
                        url_matching: 'contains' as const,
                    },
                ],
                tags: ['test', 'integration'],
            }

            const result = await createTool.handler(context, params)
            const actionData = parseToolResponse(result)

            expect(actionData.id).toBeTruthy()
            expect(actionData.name).toBe(params.name)
            expect(actionData.description).toBe(params.description)
            expect(actionData.url).toContain('/data-management/actions/')

            createdResources.actions.push(actionData.id)
        })

        it('should create an action with autocapture step', async () => {
            const params = {
                name: `Click Action ${generateUniqueKey('click')}`,
                steps: [
                    {
                        event: '$autocapture',
                        tag_name: 'button',
                        text: 'Sign Up',
                        text_matching: 'contains' as const,
                        selector: 'div.signup-form > button',
                    },
                ],
            }

            const result = await createTool.handler(context, params)
            const actionData = parseToolResponse(result)

            expect(actionData.id).toBeTruthy()
            expect(actionData.name).toBe(params.name)

            createdResources.actions.push(actionData.id)
        })

        it('should create an action with multiple steps (OR conditions)', async () => {
            const params = {
                name: `Multi-step Action ${generateUniqueKey('multi')}`,
                description: 'Action with multiple trigger conditions',
                steps: [
                    {
                        event: '$pageview',
                        url: '/pricing',
                        url_matching: 'contains' as const,
                    },
                    {
                        event: '$autocapture',
                        tag_name: 'a',
                        href: '/pricing',
                        href_matching: 'contains' as const,
                    },
                ],
            }

            const result = await createTool.handler(context, params)
            const actionData = parseToolResponse(result)

            expect(actionData.id).toBeTruthy()
            expect(actionData.name).toBe(params.name)
            expect(actionData.steps).toHaveLength(2)

            createdResources.actions.push(actionData.id)
        })

        it('should create an action with custom event', async () => {
            const params = {
                name: `Custom Event Action ${generateUniqueKey('custom')}`,
                steps: [
                    {
                        event: 'user_signed_up',
                    },
                ],
            }

            const result = await createTool.handler(context, params)
            const actionData = parseToolResponse(result)

            expect(actionData.id).toBeTruthy()
            expect(actionData.name).toBe(params.name)

            createdResources.actions.push(actionData.id)
        })
    })

    describe('actions-get-all tool', () => {
        const getAllTool = getAllActionsTool()
        const createTool = createActionTool()

        it('should list all actions', async () => {
            // Create a test action first
            const createResult = await createTool.handler(context, {
                name: `List Test Action ${generateUniqueKey('list')}`,
                steps: [{ event: '$pageview' }],
            })
            const createdAction = parseToolResponse(createResult)
            createdResources.actions.push(createdAction.id)

            // List actions
            const result = await getAllTool.handler(context, {})
            const actions = parseToolResponse(result)

            expect(Array.isArray(actions)).toBe(true)
            expect(actions.some((a: { id: number }) => a.id === createdAction.id)).toBe(true)
        })

        it('should support pagination', async () => {
            const result = await getAllTool.handler(context, {
                data: { limit: 5, offset: 0 },
            })
            const actions = parseToolResponse(result)

            expect(Array.isArray(actions)).toBe(true)
            expect(actions.length).toBeLessThanOrEqual(5)
        })
    })

    describe('action-get tool', () => {
        const getTool = getActionTool()
        const createTool = createActionTool()

        it('should get a specific action by ID', async () => {
            // Create a test action first
            const createResult = await createTool.handler(context, {
                name: `Get Test Action ${generateUniqueKey('get')}`,
                description: 'Test description for get',
                steps: [
                    {
                        event: '$pageview',
                        url: '/test',
                    },
                ],
            })
            const createdAction = parseToolResponse(createResult)
            createdResources.actions.push(createdAction.id)

            // Get the action
            const result = await getTool.handler(context, { actionId: createdAction.id })
            const actionData = parseToolResponse(result)

            expect(actionData.id).toBe(createdAction.id)
            expect(actionData.name).toBe(createdAction.name)
            expect(actionData.description).toBe('Test description for get')
            expect(actionData.url).toContain('/data-management/actions/')
        })
    })

    describe('action-update tool', () => {
        const updateTool = updateActionTool()
        const createTool = createActionTool()

        it('should update an action name and description', async () => {
            // Create a test action first
            const originalName = `Original Action ${generateUniqueKey('original')}`
            const createResult = await createTool.handler(context, {
                name: originalName,
                steps: [{ event: '$pageview' }],
            })
            const createdAction = parseToolResponse(createResult)
            createdResources.actions.push(createdAction.id)

            // Update the action
            const updatedName = `Updated Action ${generateUniqueKey('updated')}`
            const result = await updateTool.handler(context, {
                actionId: createdAction.id,
                data: {
                    name: updatedName,
                    description: 'Updated description',
                },
            })
            const updatedAction = parseToolResponse(result)

            expect(updatedAction.id).toBe(createdAction.id)
            expect(updatedAction.name).toBe(updatedName)
            expect(updatedAction.description).toBe('Updated description')
        })

        it('should update action steps', async () => {
            // Create a test action first
            const createResult = await createTool.handler(context, {
                name: `Steps Update Action ${generateUniqueKey('steps')}`,
                steps: [{ event: '$pageview' }],
            })
            const createdAction = parseToolResponse(createResult)
            createdResources.actions.push(createdAction.id)

            // Update with new steps
            const result = await updateTool.handler(context, {
                actionId: createdAction.id,
                data: {
                    steps: [
                        {
                            event: '$pageview',
                            url: '/updated-page',
                            url_matching: 'contains' as const,
                        },
                        {
                            event: '$autocapture',
                            tag_name: 'button',
                        },
                    ],
                },
            })
            const updatedAction = parseToolResponse(result)

            expect(updatedAction.id).toBe(createdAction.id)
            expect(updatedAction.steps).toHaveLength(2)
        })

        it('should update action tags', async () => {
            // Create a test action first
            const createResult = await createTool.handler(context, {
                name: `Tags Update Action ${generateUniqueKey('tags')}`,
                steps: [{ event: '$pageview' }],
                tags: ['original'],
            })
            const createdAction = parseToolResponse(createResult)
            createdResources.actions.push(createdAction.id)

            // Update tags
            const result = await updateTool.handler(context, {
                actionId: createdAction.id,
                data: {
                    tags: ['updated', 'new-tag'],
                },
            })
            const updatedAction = parseToolResponse(result)

            expect(updatedAction.id).toBe(createdAction.id)
            expect(updatedAction.tags).toContain('updated')
            expect(updatedAction.tags).toContain('new-tag')
        })
    })

    describe('action-delete tool', () => {
        const deleteTool = deleteActionTool()
        const createTool = createActionTool()
        const getAllTool = getAllActionsTool()

        it('should soft delete an action', async () => {
            // Create a test action first
            const createResult = await createTool.handler(context, {
                name: `Delete Test Action ${generateUniqueKey('delete')}`,
                steps: [{ event: '$pageview' }],
            })
            const createdAction = parseToolResponse(createResult)
            // Don't add to createdResources since we're deleting it

            // Delete the action
            const deleteResult = await deleteTool.handler(context, { actionId: createdAction.id })
            const deleteData = parseToolResponse(deleteResult)

            expect(deleteData.success).toBe(true)

            // Verify it's no longer in the list
            const listResult = await getAllTool.handler(context, {})
            const actions = parseToolResponse(listResult)
            expect(actions.some((a: { id: number }) => a.id === createdAction.id)).toBe(false)
        })
    })
})
