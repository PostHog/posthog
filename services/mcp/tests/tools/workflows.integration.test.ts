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
        // Hard delete is intentionally not exposed as an MCP tool, but the underlying API
        // endpoint still exists. Call it directly for teardown so we actually remove the rows
        // instead of leaving archived workflows behind in the shared integration env.
        const projectId = await context.stateManager.getProjectId()
        for (const id of createdWorkflowIds) {
            try {
                await context.api.request({
                    method: 'DELETE',
                    path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(id)}/`,
                })
            } catch {
                // Best effort — workflow may already be gone
            }
        }
        createdWorkflowIds.length = 0
    })

    function makeWorkflowParams(overrides: Record<string, unknown> = {}): Record<string, unknown> {
        const ts = Date.now()
        return {
            name: `mcp-test-${generateUniqueKey('wf')}`,
            status: 'draft',
            actions: [
                {
                    id: 'trigger_node',
                    name: 'Trigger',
                    type: 'trigger',
                    created_at: ts,
                    updated_at: ts,
                    config: { type: 'event', filters: { events: [] } },
                },
                {
                    id: 'exit_node',
                    name: 'Exit',
                    type: 'exit',
                    created_at: ts,
                    updated_at: ts,
                    config: { reason: 'Default exit' },
                },
            ],
            edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
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
                // No workflows in this environment — nothing to fetch.
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

    describe('workflows-create tool', () => {
        it('should create a draft workflow with one trigger and one exit', async () => {
            const params = makeWorkflowParams()
            const result = await createTool.handler(context, params)
            const workflow = parseToolResponse(result)
            createdWorkflowIds.push(workflow.id)

            expect(workflow.id).toBeTypeOf('string')
            expect(workflow.name).toBe(params.name)
            expect(workflow.status).toBe('draft')
            expect(workflow.version).toBeTypeOf('number')
            expect(Array.isArray(workflow.actions)).toBe(true)
            expect(workflow.actions).toHaveLength(2)
            expect(workflow._posthogUrl).toContain(`/pipeline/destinations/hog-${workflow.id}`)
        })

        it('should reject a workflow without exactly one trigger action', async () => {
            const params = makeWorkflowParams({
                actions: [
                    {
                        id: 'exit_node',
                        name: 'Exit',
                        type: 'exit',
                        config: { reason: 'Default exit' },
                    },
                ],
                edges: [],
            })
            await expect(createTool.handler(context, params)).rejects.toThrow()
        })
    })

    describe('workflows-update tool', () => {
        it('should partially update a workflow name', async () => {
            const created = parseToolResponse(await createTool.handler(context, makeWorkflowParams()))
            createdWorkflowIds.push(created.id)

            const renamed = parseToolResponse(
                await updateTool.handler(context, { id: created.id, name: 'mcp-test-renamed' })
            )

            expect(renamed.id).toBe(created.id)
            expect(renamed.name).toBe('mcp-test-renamed')
        })

        it('should archive a workflow via status transition', async () => {
            const created = parseToolResponse(await createTool.handler(context, makeWorkflowParams()))
            createdWorkflowIds.push(created.id)

            const archived = parseToolResponse(
                await updateTool.handler(context, { id: created.id, status: 'archived' })
            )

            expect(archived.status).toBe('archived')
        })
    })

    describe('workflows-run tool', () => {
        it('should test-invoke a workflow with mocked async functions', async () => {
            const created = parseToolResponse(await createTool.handler(context, makeWorkflowParams()))
            createdWorkflowIds.push(created.id)

            const result = await runTool.handler(context, {
                id: created.id,
                globals: { event: { event: '$pageview', distinct_id: 'test-distinct-id' } },
                mock_async_functions: true,
            })
            const data = parseToolResponse(result)

            // The exact shape depends on the executor; assert we got *something* back.
            expect(data).not.toBeUndefined()
        })
    })

    describe('full lifecycle', () => {
        it('should create → update → run → archive', async () => {
            const created = parseToolResponse(await createTool.handler(context, makeWorkflowParams()))
            const id = created.id
            createdWorkflowIds.push(id)

            const updated = parseToolResponse(await updateTool.handler(context, { id, name: 'mcp-lifecycle-test' }))
            expect(updated.name).toBe('mcp-lifecycle-test')

            const runResult = await runTool.handler(context, {
                id,
                globals: { event: { event: '$pageview', distinct_id: 'lifecycle-test' } },
                mock_async_functions: true,
            })
            expect(parseToolResponse(runResult)).not.toBeUndefined()

            const archived = parseToolResponse(await updateTool.handler(context, { id, status: 'archived' }))
            expect(archived.status).toBe('archived')
        })
    })
})
