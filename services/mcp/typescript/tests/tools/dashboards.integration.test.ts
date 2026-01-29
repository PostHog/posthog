import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    SAMPLE_HOGQL_QUERIES,
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
import addInsightToDashboardTool from '@/tools/dashboards/addInsight'
import createDashboardTool from '@/tools/dashboards/create'
import deleteDashboardTool from '@/tools/dashboards/delete'
import getDashboardTool from '@/tools/dashboards/get'
import getAllDashboardsTool from '@/tools/dashboards/getAll'
import reorderDashboardTilesTool from '@/tools/dashboards/reorderTiles'
import updateDashboardTool from '@/tools/dashboards/update'
import createInsightTool from '@/tools/insights/create'
import type { Context } from '@/tools/types'

describe('Dashboards', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
        annotations: []
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

            expect(dashboardData.id).toBeTruthy()
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

            expect(dashboardData.id).toBeTruthy()
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

    describe('reorder-dashboard-tiles tool', () => {
        const createDashboard = createDashboardTool()
        const createInsight = createInsightTool()
        const addInsight = addInsightToDashboardTool()
        const reorderTiles = reorderDashboardTilesTool()
        const getDashboard = getDashboardTool()
        const deleteDashboard = deleteDashboardTool()

        it('should reorder tiles on a dashboard', async () => {
            // Create a dashboard
            const dashboardResult = await createDashboard.handler(context, {
                data: {
                    name: generateUniqueKey('Reorder Test Dashboard'),
                    description: 'Dashboard for testing tile reordering',
                    pinned: false,
                },
            })
            const dashboard = parseToolResponse(dashboardResult)
            createdResources.dashboards.push(dashboard.id)

            // Create two insights
            const insight1Result = await createInsight.handler(context, {
                data: {
                    name: generateUniqueKey('Insight 1'),
                    description: 'First insight',
                    query: SAMPLE_HOGQL_QUERIES.pageviews,
                    favorited: false,
                },
            })
            const insight1 = parseToolResponse(insight1Result)
            createdResources.insights.push(insight1.id)

            const insight2Result = await createInsight.handler(context, {
                data: {
                    name: generateUniqueKey('Insight 2'),
                    description: 'Second insight',
                    query: SAMPLE_HOGQL_QUERIES.topEvents,
                    favorited: false,
                },
            })
            const insight2 = parseToolResponse(insight2Result)
            createdResources.insights.push(insight2.id)

            // Add insights to dashboard
            await addInsight.handler(context, {
                data: {
                    insightId: insight1.short_id,
                    dashboardId: dashboard.id,
                },
            })
            await addInsight.handler(context, {
                data: {
                    insightId: insight2.short_id,
                    dashboardId: dashboard.id,
                },
            })

            // Get the dashboard to see the tile IDs
            const dashboardWithTilesResult = await getDashboard.handler(context, {
                dashboardId: dashboard.id,
            })
            const dashboardWithTiles = parseToolResponse(dashboardWithTilesResult)

            expect(dashboardWithTiles.tiles).toBeTruthy()
            expect(dashboardWithTiles.tiles.length).toBeGreaterThanOrEqual(2)

            // Get the tile IDs (filter out null tiles)
            const tileIds = dashboardWithTiles.tiles
                .filter((tile: any) => tile !== null && tile.id !== undefined)
                .map((tile: any) => tile.id)

            // Reorder tiles (reverse the order)
            const reversedTileOrder = [...tileIds].reverse()
            const reorderResult = await reorderTiles.handler(context, {
                dashboardId: dashboard.id,
                tileOrder: reversedTileOrder,
            })
            const reorderResponse = parseToolResponse(reorderResult)

            expect(reorderResponse.success).toBe(true)
            expect(reorderResponse.message).toContain('Successfully reordered')
            expect(reorderResponse.tiles).toBeTruthy()
            expect(reorderResponse.url).toContain('/dashboard/')

            // Clean up
            await deleteDashboard.handler(context, { dashboardId: dashboard.id })
            createdResources.dashboards = createdResources.dashboards.filter((id) => id !== dashboard.id)
        })
    })
})
