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
import { GENERATED_TOOLS } from '@/tools/generated/workflows'
import type { Context } from '@/tools/types'

describe('Workflows', { concurrent: false }, () => {
    let context: Context

    const listTool = GENERATED_TOOLS['workflows-list']!()
    const getTool = GENERATED_TOOLS['workflows-get']!()
    const createTool = GENERATED_TOOLS['workflows-create']!()
    const updateTool = GENERATED_TOOLS['workflows-update']!()
    const deleteTool = GENERATED_TOOLS['workflows-delete']!()
    const runTool = GENERATED_TOOLS['workflows-run']!()
    const logsTool = GENERATED_TOOLS['hog-flows-logs-retrieve']!()
    const metricsTool = GENERATED_TOOLS['hog-flows-metrics-retrieve']!()

    const createdWorkflowIds: string[] = []

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        for (const id of createdWorkflowIds) {
            try {
                await deleteTool.handler(context, { id })
            } catch {
                // Best effort — may already be deleted
            }
        }
        createdWorkflowIds.length = 0
    })

    function makeWorkflowParams(overrides: Record<string, unknown> = {}): Record<string, unknown> {
        const ts = Date.now()
        return {
            name: `test-workflow-${generateUniqueKey('wf')}`,
            actions: [
                {
                    id: 'trigger_node',
                    name: 'Trigger',
                    type: 'trigger',
                    created_at: ts,
                    updated_at: ts,
                    config: {
                        type: 'event',
                        filters: {
                            events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
                        },
                    },
                },
            ],
            edges: [],
            ...overrides,
        }
    }

    describe('workflows-list tool', () => {
        it('should list workflows and return paginated structure', async () => {
            const result = await listTool.handler(context, {})
            const data = parseToolResponse(result)

            expect(typeof data.count).toBe('number')
            expect(Array.isArray(data.results)).toBe(true)
        })

        it('should respect the limit parameter', async () => {
            const result = await listTool.handler(context, { limit: 1 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(1)
        })

        it('should respect the offset parameter', async () => {
            const allResult = await listTool.handler(context, { limit: 100 })
            const all = parseToolResponse(allResult)

            const pagedResult = await listTool.handler(context, { offset: 1, limit: 100 })
            const paged = parseToolResponse(pagedResult)

            // Paging forward by one should yield at most (total − 1) results.
            expect(paged.results.length).toBeLessThanOrEqual(Math.max(0, all.results.length - 1))
        })
    })

    describe('workflows-get tool', () => {
        it('should return a valid workflow when given a UUID from the list', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                return
            }

            const firstId: string = workflows[0].id
            const result = await getTool.handler(context, { id: firstId })
            const workflow = parseToolResponse(result)

            expect(workflow.id).toBe(firstId)
            expect(workflow.name == null || typeof workflow.name === 'string').toBe(true)
            expect(typeof workflow.version).toBe('number')
            expect(['draft', 'active', 'archived']).toContain(workflow.status)
            expect(Array.isArray(workflow.actions)).toBe(true)
            expect(workflow).toHaveProperty('trigger')
            expect(workflow).toHaveProperty('edges')
            expect(workflow).toHaveProperty('exit_condition')
        })

        it('should return an error for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()

            await expect(getTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('workflows-create tool', () => {
        it('should create a minimal draft workflow', async () => {
            const params = makeWorkflowParams()
            const result = await createTool.handler(context, params)
            const workflow = parseToolResponse(result)
            createdWorkflowIds.push(workflow.id)

            expect(workflow.id).toBeTruthy()
            expect(workflow.name).toBe(params.name)
            expect(workflow.status).toBe('draft')
            expect(Array.isArray(workflow.actions)).toBe(true)
            expect(workflow.actions.length).toBe(1)
            expect(workflow.actions[0].type).toBe('trigger')
        })

        it('should create a workflow with description and exit_condition', async () => {
            const params = makeWorkflowParams({
                description: 'A test workflow with exit condition',
                exit_condition: 'exit_only_at_end',
            })
            const result = await createTool.handler(context, params)
            const workflow = parseToolResponse(result)
            createdWorkflowIds.push(workflow.id)

            expect(workflow.description).toBe('A test workflow with exit condition')
            expect(workflow.exit_condition).toBe('exit_only_at_end')
        })
    })

    describe('workflows-update tool', () => {
        it('should update the workflow name', async () => {
            const created = await createTool.handler(context, makeWorkflowParams())
            const workflow = parseToolResponse(created)
            createdWorkflowIds.push(workflow.id)

            const newName = `renamed-${generateUniqueKey('upd')}`
            const result = await updateTool.handler(context, { id: workflow.id, name: newName })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(workflow.id)
            expect(updated.name).toBe(newName)
        })

        it('should update status from draft to active', async () => {
            const created = await createTool.handler(context, makeWorkflowParams())
            const workflow = parseToolResponse(created)
            createdWorkflowIds.push(workflow.id)

            const result = await updateTool.handler(context, { id: workflow.id, status: 'active' })
            const updated = parseToolResponse(result)

            expect(updated.status).toBe('active')
        })
    })

    describe('workflows-delete tool', () => {
        it('should delete a workflow and verify it is gone', async () => {
            const created = await createTool.handler(context, makeWorkflowParams())
            const workflow = parseToolResponse(created)

            await deleteTool.handler(context, { id: workflow.id })
            await expect(getTool.handler(context, { id: workflow.id })).rejects.toThrow()
        })

        it('should throw for a non-existent UUID', async () => {
            await expect(deleteTool.handler(context, { id: crypto.randomUUID() })).rejects.toThrow()
        })
    })

    describe('workflows-run tool', () => {
        it('should test-run a workflow with mock globals', async () => {
            const created = await createTool.handler(context, makeWorkflowParams())
            const workflow = parseToolResponse(created)
            createdWorkflowIds.push(workflow.id)

            try {
                const result = await runTool.handler(context, {
                    id: workflow.id,
                    globals: {
                        event: '$pageview',
                    },
                    mock_async_functions: true,
                })
                // If the plugin server is running, we get a response
                expect(result).toBeTruthy()
            } catch (error: unknown) {
                // Plugin server may not be running in CI — connection errors are expected
                const message = error instanceof Error ? error.message : String(error)
                expect(message).toMatch(/502|503|connection|ECONNREFUSED|fetch failed/i)
            }
        })
    })

    describe('full lifecycle', () => {
        it('should support create → get → update → delete', async () => {
            // Create
            const created = await createTool.handler(context, makeWorkflowParams())
            const workflow = parseToolResponse(created)
            expect(workflow.id).toBeTruthy()
            expect(workflow.status).toBe('draft')

            // Get
            const retrieved = await getTool.handler(context, { id: workflow.id })
            expect(parseToolResponse(retrieved).id).toBe(workflow.id)

            // Update
            const newName = `lifecycle-${generateUniqueKey('lc')}`
            const updated = await updateTool.handler(context, { id: workflow.id, name: newName })
            expect(parseToolResponse(updated).name).toBe(newName)

            // Verify appears in list
            const listResult = await listTool.handler(context, {})
            const { results } = parseToolResponse(listResult)
            expect(results.some((w: { id: string }) => w.id === workflow.id)).toBe(true)

            // Delete
            await deleteTool.handler(context, { id: workflow.id })
            await expect(getTool.handler(context, { id: workflow.id })).rejects.toThrow()
        })
    })

    describe('hog-flows-logs-retrieve tool', () => {
        it('should return log entries for a workflow', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                return
            }

            const result = await logsTool.handler(context, { id: workflows[0].id })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
        })

        it('should accept limit and level parameters', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                return
            }

            const result = await logsTool.handler(context, {
                id: workflows[0].id,
                limit: 5,
                level: 'ERROR',
            })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(5)
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(logsTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('hog-flows-metrics-retrieve tool', () => {
        it('should return metrics for a workflow', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                return
            }

            const result = await metricsTool.handler(context, { id: workflows[0].id })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.labels)).toBe(true)
            expect(Array.isArray(data.series)).toBe(true)
        })

        it('should accept interval parameter', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                return
            }

            const result = await metricsTool.handler(context, {
                id: workflows[0].id,
                interval: 'day',
            })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.labels)).toBe(true)
            expect(Array.isArray(data.series)).toBe(true)
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(metricsTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })
})
