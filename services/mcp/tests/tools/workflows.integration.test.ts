import { beforeAll, describe, expect, it } from 'vitest'

import {
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
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
    const updateTool = GENERATED_TOOLS['workflows-partial-update']!()
    const destroyTool = GENERATED_TOOLS['workflows-destroy']!()
    const bulkDeleteTool = GENERATED_TOOLS['workflows-bulk-delete']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

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

    describe('workflows-create tool', () => {
        it('should create a minimal draft workflow and return an id', async () => {
            const workflow = await createTestWorkflow(context)

            expect(typeof workflow.id).toBe('string')
            expect(workflow.status).toBe('draft')

            await archiveWorkflow(workflow.id)
        })

        it('should create a workflow with description', async () => {
            const desc = 'Integration test description'
            const workflow = await createTestWorkflow(context, { description: desc })

            expect(workflow.description).toBe(desc)

            await archiveWorkflow(workflow.id)
        })

        it('should create a workflow with name and description', async () => {
            const name = `Named workflow ${crypto.randomUUID()}`
            const desc = 'Both fields set'
            const workflow = await createTestWorkflow(context, { name, description: desc })

            expect(workflow.name).toBe(name)
            expect(workflow.description).toBe(desc)

            await archiveWorkflow(workflow.id)
        })

        it('should create a workflow with edges between actions', async () => {
            const now = Date.now()
            const workflow = await createTestWorkflow(context, {
                actions: [
                    {
                        id: 'trigger_node',
                        name: 'Trigger',
                        type: 'trigger',
                        created_at: now,
                        updated_at: now,
                        config: {
                            type: 'event',
                            filters: {
                                events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
                            },
                        },
                    },
                    {
                        id: 'function_node',
                        name: 'Function',
                        type: 'function',
                        created_at: now,
                        updated_at: now,
                        config: {
                            template_id: 'template-webhook',
                            inputs: {},
                        },
                    },
                ],
                edges: [{ from: 'trigger_node', to: 'function_node', type: 'continue' }],
            })

            expect(workflow.edges).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ from: 'trigger_node', to: 'function_node', type: 'continue' }),
                ])
            )

            await archiveWorkflow(workflow.id)
        })

        it('should create a workflow with variables', async () => {
            const variables = [{ key: 'test_var', value: 'hello' }]
            const workflow = await createTestWorkflow(context, { variables })

            expect(workflow.variables).toEqual(
                expect.arrayContaining([expect.objectContaining({ key: 'test_var', value: 'hello' })])
            )

            await archiveWorkflow(workflow.id)
        })

        it('should reject creation without a trigger action', async () => {
            await expect(
                createTool.handler(context, {
                    name: `No trigger ${crypto.randomUUID()}`,
                    actions: [],
                    edges: [],
                })
            ).rejects.toThrow()
        })

        it('should create a workflow with exit_condition', async () => {
            const workflow = await createTestWorkflow(context, {
                exit_condition: 'exit_on_conversion',
            })

            expect(workflow.exit_condition).toBe('exit_on_conversion')

            await archiveWorkflow(workflow.id)
        })
    })

    describe('workflows-partial-update tool', () => {
        it('should update the name of an existing workflow', async () => {
            const created = await createTestWorkflow(context)

            const newName = `Updated name ${crypto.randomUUID()}`
            const updateResult = await updateTool.handler(context, { id: created.id, name: newName })
            const updated = parseToolResponse(updateResult)

            expect(updated.id).toBe(created.id)
            expect(updated.name).toBe(newName)

            await archiveWorkflow(created.id)
        })

        it('should update the description', async () => {
            const created = await createTestWorkflow(context)

            const updateResult = await updateTool.handler(context, {
                id: created.id,
                description: 'Patched description',
            })
            const updated = parseToolResponse(updateResult)

            expect(updated.description).toBe('Patched description')

            await archiveWorkflow(created.id)
        })

        it('should transition status from draft to archived', async () => {
            const created = await createTestWorkflow(context)
            expect(created.status).toBe('draft')

            const updateResult = await updateTool.handler(context, { id: created.id, status: 'archived' })
            const updated = parseToolResponse(updateResult)

            expect(updated.status).toBe('archived')
        })

        it('should transition status through the full lifecycle: draft → active → archived', async () => {
            const created = await createTestWorkflow(context)
            expect(created.status).toBe('draft')

            const activeResult = await updateTool.handler(context, { id: created.id, status: 'active' })
            expect(parseToolResponse(activeResult).status).toBe('active')

            const archivedResult = await updateTool.handler(context, { id: created.id, status: 'archived' })
            expect(parseToolResponse(archivedResult).status).toBe('archived')
        })

        it('should update edges', async () => {
            const now = Date.now()
            const created = await createTestWorkflow(context, {
                actions: [
                    {
                        id: 'trigger_node',
                        name: 'Trigger',
                        type: 'trigger',
                        created_at: now,
                        updated_at: now,
                        config: {
                            type: 'event',
                            filters: {
                                events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
                            },
                        },
                    },
                    {
                        id: 'fn_node',
                        name: 'Function',
                        type: 'function',
                        created_at: now,
                        updated_at: now,
                        config: { template_id: 'template-webhook', inputs: {} },
                    },
                ],
            })

            const newEdges = [{ from: 'trigger_node', to: 'fn_node', type: 'continue' }]
            const updateResult = await updateTool.handler(context, { id: created.id, edges: newEdges })
            const updated = parseToolResponse(updateResult)

            expect(updated.edges).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ from: 'trigger_node', to: 'fn_node', type: 'continue' }),
                ])
            )

            await archiveWorkflow(created.id)
        })

        it('should update variables', async () => {
            const created = await createTestWorkflow(context)

            const vars = [{ key: 'patched_var', value: 'patched_value' }]
            const updateResult = await updateTool.handler(context, { id: created.id, variables: vars })
            const updated = parseToolResponse(updateResult)

            expect(updated.variables).toEqual(
                expect.arrayContaining([expect.objectContaining({ key: 'patched_var', value: 'patched_value' })])
            )

            await archiveWorkflow(created.id)
        })

        it('should handle an empty patch without error', async () => {
            const created = await createTestWorkflow(context, { description: 'original' })

            const updateResult = await updateTool.handler(context, { id: created.id })
            const updated = parseToolResponse(updateResult)

            expect(updated.id).toBe(created.id)
            expect(updated.description).toBe('original')

            await archiveWorkflow(created.id)
        })
    })

    describe('workflows-destroy tool', () => {
        it('should delete an archived workflow', async () => {
            const created = await createTestWorkflow(context)
            await archiveWorkflow(created.id)

            await destroyTool.handler(context, { id: created.id })

            await expect(getTool.handler(context, { id: created.id })).rejects.toThrow()
        })

        it('should fail for a non-existent UUID', async () => {
            await expect(destroyTool.handler(context, { id: crypto.randomUUID() })).rejects.toThrow()
        })
    })

    describe('workflows-bulk-delete tool', () => {
        it('should bulk-delete archived workflows', async () => {
            const [first, second] = await Promise.all([createTestWorkflow(context), createTestWorkflow(context)])
            await Promise.all([archiveWorkflow(first.id), archiveWorkflow(second.id)])

            const result = await bulkDeleteTool.handler(context, { ids: [first.id, second.id] })
            const data = parseToolResponse(result)

            expect(data.deleted).toBe(2)
        })

        it('should skip non-archived workflows', async () => {
            const created = await createTestWorkflow(context)

            const result = await bulkDeleteTool.handler(context, { ids: [created.id] })
            const data = parseToolResponse(result)

            expect(data.deleted).toBe(0)

            await archiveWorkflow(created.id)
        })
    })

    async function createTestWorkflow(ctx: Context, overrides: Record<string, unknown> = {}): Promise<any> {
        const now = Date.now()
        const result = await createTool.handler(ctx, {
            name: `MCP integration test workflow ${crypto.randomUUID()}`,
            actions: [
                {
                    id: 'trigger_node',
                    name: 'Trigger',
                    type: 'trigger',
                    created_at: now,
                    updated_at: now,
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
        })
        return parseToolResponse(result)
    }

    async function archiveWorkflow(id: string): Promise<void> {
        await updateTool.handler(context, { id, status: 'archived' })
    }
})
