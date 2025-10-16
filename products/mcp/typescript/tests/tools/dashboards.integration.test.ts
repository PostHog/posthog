import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import {
    validateEnvironmentVariables,
    createTestClient,
    createTestContext,
    setActiveProjectAndOrg,
    cleanupResources,
    parseToolResponse,
    generateUniqueKey,
    TEST_PROJECT_ID,
    TEST_ORG_ID,
    type CreatedResources,
} from '@/shared/test-utils'
import createDashboardTool from '@/tools/dashboards/create'
import updateDashboardTool from '@/tools/dashboards/update'
import deleteDashboardTool from '@/tools/dashboards/delete'
import getAllDashboardsTool from '@/tools/dashboards/getAll'
import getDashboardTool from '@/tools/dashboards/get'
import type { Context } from '@/tools/types'

describe('Dashboards', { concurrent: false }, () => {
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

    describe('create-dashboard tool', () => {
        const createTool = createDashboardTool()

        it('should create a dashboard with minimal fields', async () => {
            const params = {
                data: {
                    name: generateUniqueKey('Test Dashboard'),
                    description: 'Integration test dashboard',
                    pinned: false,
                },
            }

            const result = await createTool.handler(context, params)
            const dashboardData = parseToolResponse(result)

            expect(dashboardData.id).toBeDefined()
            expect(dashboardData.name).toBe(params.data.name)
            expect(dashboardData.url).toContain('/dashboard/')

            createdResources.dashboards.push(dashboardData.id)
        })

        it('should create a dashboard with tags', async () => {
            const params = {
                data: {
                    name: generateUniqueKey('Tagged Dashboard'),
                    description: 'Dashboard with tags',
                    tags: ['test', 'integration'],
                    pinned: false,
                },
            }

            const result = await createTool.handler(context, params)
            const dashboardData = parseToolResponse(result)

            expect(dashboardData.id).toBeDefined()
            expect(dashboardData.name).toBe(params.data.name)

            createdResources.dashboards.push(dashboardData.id)
        })
    })

    describe('update-dashboard tool', () => {
        const createTool = createDashboardTool()
        const updateTool = updateDashboardTool()

        it('should update dashboard name and description', async () => {
            const createParams = {
                data: {
                    name: generateUniqueKey('Original Dashboard'),
                    description: 'Original description',
                    pinned: false,
                },
            }

            const createResult = await createTool.handler(context, createParams)
            const createdDashboard = parseToolResponse(createResult)
            createdResources.dashboards.push(createdDashboard.id)

            const updateParams = {
                dashboardId: createdDashboard.id,
                data: {
                    name: 'Updated Dashboard Name',
                    description: 'Updated description',
                },
            }

            const updateResult = await updateTool.handler(context, updateParams)
            const updatedDashboard = parseToolResponse(updateResult)

            expect(updatedDashboard.id).toBe(createdDashboard.id)
            expect(updatedDashboard.name).toBe(updateParams.data.name)
        })
    })

    describe('get-all-dashboards tool', () => {
        const getAllTool = getAllDashboardsTool()

        it('should return dashboards with proper structure', async () => {
            const result = await getAllTool.handler(context, {})
            const dashboards = parseToolResponse(result)

            expect(Array.isArray(dashboards)).toBe(true)
            if (dashboards.length > 0) {
                const dashboard = dashboards[0]
                expect(dashboard).toHaveProperty('id')
                expect(dashboard).toHaveProperty('name')
            }
        })
    })

    describe('get-dashboard tool', () => {
        const createTool = createDashboardTool()
        const getTool = getDashboardTool()

        it('should get a specific dashboard by ID', async () => {
            const createParams = {
                data: {
                    name: generateUniqueKey('Get Test Dashboard'),
                    description: 'Test dashboard for get operation',
                    pinned: false,
                },
            }

            const createResult = await createTool.handler(context, createParams)
            const createdDashboard = parseToolResponse(createResult)
            createdResources.dashboards.push(createdDashboard.id)

            const result = await getTool.handler(context, { dashboardId: createdDashboard.id })
            const retrievedDashboard = parseToolResponse(result)

            expect(retrievedDashboard.id).toBe(createdDashboard.id)
            expect(retrievedDashboard.name).toBe(createParams.data.name)
        })
    })

    describe('delete-dashboard tool', () => {
        const createTool = createDashboardTool()
        const deleteTool = deleteDashboardTool()

        it('should delete a dashboard', async () => {
            const createParams = {
                data: {
                    name: generateUniqueKey('Delete Test Dashboard'),
                    description: 'Test dashboard for deletion',
                    pinned: false,
                },
            }

            const createResult = await createTool.handler(context, createParams)
            const createdDashboard = parseToolResponse(createResult)

            const deleteResult = await deleteTool.handler(context, {
                dashboardId: createdDashboard.id,
            })
            const deleteResponse = parseToolResponse(deleteResult)

            expect(deleteResponse.success).toBe(true)
            expect(deleteResponse.message).toContain('deleted successfully')
        })
    })

    describe('Dashboard workflow', () => {
        it('should support full CRUD workflow', async () => {
            const createTool = createDashboardTool()
            const updateTool = updateDashboardTool()
            const getTool = getDashboardTool()
            const deleteTool = deleteDashboardTool()

            const createParams = {
                data: {
                    name: generateUniqueKey('Workflow Test Dashboard'),
                    description: 'Testing full workflow',
                    pinned: false,
                },
            }

            const createResult = await createTool.handler(context, createParams)
            const createdDashboard = parseToolResponse(createResult)

            const getResult = await getTool.handler(context, { dashboardId: createdDashboard.id })
            const retrievedDashboard = parseToolResponse(getResult)
            expect(retrievedDashboard.id).toBe(createdDashboard.id)

            const updateParams = {
                dashboardId: createdDashboard.id,
                data: {
                    name: 'Updated Workflow Dashboard',
                    description: 'Updated workflow description',
                },
            }

            const updateResult = await updateTool.handler(context, updateParams)
            const updatedDashboard = parseToolResponse(updateResult)
            expect(updatedDashboard.name).toBe(updateParams.data.name)

            const deleteResult = await deleteTool.handler(context, {
                dashboardId: createdDashboard.id,
            })
            const deleteResponse = parseToolResponse(deleteResult)
            expect(deleteResponse.success).toBe(true)
        })
    })
})
