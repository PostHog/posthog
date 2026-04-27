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
import { GENERATED_TOOLS } from '@/tools/generated/tasks'
import type { Context } from '@/tools/types'

describe('Tasks', { concurrent: false }, () => {
    let context: Context
    const createdTaskIds: string[] = []

    const createTool = GENERATED_TOOLS['tasks-create']!()
    const listTool = GENERATED_TOOLS['tasks-list']!()
    const retrieveTool = GENERATED_TOOLS['tasks-retrieve']!()
    const updateTool = GENERATED_TOOLS['tasks-partial-update']!()
    const deleteTool = GENERATED_TOOLS['tasks-destroy']!()
    const runsListTool = GENERATED_TOOLS['tasks-runs-list']!()
    const runsRetrieveTool = GENERATED_TOOLS['tasks-runs-retrieve']!()
    const runsSessionLogsTool = GENERATED_TOOLS['tasks-runs-session-logs-retrieve']!()
    const runCreateTool = GENERATED_TOOLS['tasks-run-create']!()
    const sandboxListTool = GENERATED_TOOLS['sandbox-list']!()
    const sandboxRetrieveTool = GENERATED_TOOLS['sandbox-retrieve']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        for (const id of createdTaskIds) {
            try {
                await deleteTool.handler(context, { id })
            } catch {
                // best effort — task may already be deleted
            }
        }
        createdTaskIds.length = 0
    })

    describe('tasks-create tool', () => {
        it('should create a task with title, description, and repository', async () => {
            const title = `Test task ${generateUniqueKey('task')}`
            const description = 'Integration test task description'
            const params = {
                title,
                description,
                origin_product: 'user_created' as const,
                repository: 'posthog/posthog',
            }

            const result = await createTool.handler(context, params)
            const task = parseToolResponse(result)

            expect(task.id).toBeTruthy()
            expect(task.title).toBe(title)
            expect(task.description).toBe(description)
            expect(task.origin_product).toBe('user_created')
            expect(task.repository).toBe('posthog/posthog')
            expect(task._posthogUrl).toContain('/tasks/')

            createdTaskIds.push(task.id)
        })

        it('should auto-generate a title when only description is provided', async () => {
            const description = `Auto-titled task ${generateUniqueKey('auto')}`
            const params = {
                description,
                origin_product: 'user_created' as const,
            }

            const result = await createTool.handler(context, params)
            const task = parseToolResponse(result)

            expect(task.id).toBeTruthy()
            expect(task.title).toBeTruthy()
            expect(task.description).toBe(description)
            expect(task.title_manually_set).toBe(false)

            createdTaskIds.push(task.id)
        })
    })

    describe('tasks-list tool', () => {
        it('should list tasks including a newly created one', async () => {
            const createResult = await createTool.handler(context, {
                title: `List test task ${generateUniqueKey('list')}`,
                description: 'List integration test',
                origin_product: 'user_created' as const,
            })
            const created = parseToolResponse(createResult)
            createdTaskIds.push(created.id)

            const result = await listTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.some((t: { id: string }) => t.id === created.id)).toBe(true)
        })

        it('should respect the limit query parameter', async () => {
            const result = await listTool.handler(context, { limit: 2, offset: 0 })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeLessThanOrEqual(2)
        })

        it('should filter by repository', async () => {
            const repository = `test-org/${generateUniqueKey('repo').toLowerCase()}`
            const createResult = await createTool.handler(context, {
                title: `Filter test task ${generateUniqueKey('filter')}`,
                description: 'Filter integration test',
                origin_product: 'user_created' as const,
                repository,
            })
            const created = parseToolResponse(createResult)
            createdTaskIds.push(created.id)

            const result = await listTool.handler(context, { repository })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeGreaterThan(0)
            for (const task of response.results) {
                expect(task.repository).toBe(repository)
            }
        })
    })

    describe('tasks-retrieve tool', () => {
        it('should retrieve a task by ID', async () => {
            const title = `Retrieve test ${generateUniqueKey('retrieve')}`
            const createResult = await createTool.handler(context, {
                title,
                description: 'Retrieve integration test',
                origin_product: 'user_created' as const,
            })
            const created = parseToolResponse(createResult)
            createdTaskIds.push(created.id)

            const result = await retrieveTool.handler(context, { id: created.id })
            const task = parseToolResponse(result)

            expect(task.id).toBe(created.id)
            expect(task.title).toBe(title)
        })
    })

    describe('tasks-partial-update tool', () => {
        it('should update task title', async () => {
            const createResult = await createTool.handler(context, {
                title: `Original ${generateUniqueKey('orig')}`,
                description: 'Update integration test',
                origin_product: 'user_created' as const,
            })
            const created = parseToolResponse(createResult)
            createdTaskIds.push(created.id)

            const newTitle = `Updated ${generateUniqueKey('upd')}`
            const result = await updateTool.handler(context, {
                id: created.id,
                title: newTitle,
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.title).toBe(newTitle)
        })

        it('should update task description', async () => {
            const createResult = await createTool.handler(context, {
                title: `Desc update ${generateUniqueKey('desc')}`,
                description: 'Original description',
                origin_product: 'user_created' as const,
            })
            const created = parseToolResponse(createResult)
            createdTaskIds.push(created.id)

            const newDescription = `Updated description ${generateUniqueKey('desc-upd')}`
            const result = await updateTool.handler(context, {
                id: created.id,
                description: newDescription,
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.description).toBe(newDescription)
        })

        it('should update task repository', async () => {
            const createResult = await createTool.handler(context, {
                title: `Repo update ${generateUniqueKey('repo')}`,
                description: 'Repo update integration test',
                origin_product: 'user_created' as const,
                repository: 'posthog/posthog',
            })
            const created = parseToolResponse(createResult)
            createdTaskIds.push(created.id)

            const result = await updateTool.handler(context, {
                id: created.id,
                repository: 'posthog/posthog-js',
            })
            const updated = parseToolResponse(result)

            expect(updated.id).toBe(created.id)
            expect(updated.repository).toBe('posthog/posthog-js')
        })
    })

    describe('tasks-destroy tool', () => {
        it('should soft-delete a task and remove it from list results', async () => {
            const createResult = await createTool.handler(context, {
                title: `Delete test ${generateUniqueKey('del')}`,
                description: 'Delete integration test',
                origin_product: 'user_created' as const,
            })
            const created = parseToolResponse(createResult)
            // Don't track for cleanup since we're deleting it here

            await deleteTool.handler(context, { id: created.id })

            const listResult = await listTool.handler(context, {})
            const response = parseToolResponse(listResult)
            expect(response.results.some((t: { id: string }) => t.id === created.id)).toBe(false)
        })
    })

    describe('tasks-run-create tool', () => {
        it('should create and queue a run for a task', async () => {
            const createResult = await createTool.handler(context, {
                title: `Run test ${generateUniqueKey('run')}`,
                description: 'Run creation integration test',
                origin_product: 'user_created' as const,
            })
            const created = parseToolResponse(createResult)
            createdTaskIds.push(created.id)

            const result = await runCreateTool.handler(context, { id: created.id })
            const task = parseToolResponse(result)

            expect(task.id).toBe(created.id)
            expect(task.title).toBeTruthy()
            expect(task.latest_run).toBeTruthy()
            expect(task.latest_run.status).toBeTruthy()
            expect(task._posthogUrl).toContain('/tasks/')
        })
    })

    describe('tasks-runs-list tool', () => {
        it('should return an empty list for a task with no runs', async () => {
            const createResult = await createTool.handler(context, {
                title: `Runs list test ${generateUniqueKey('runs')}`,
                description: 'Runs list integration test',
                origin_product: 'user_created' as const,
            })
            const created = parseToolResponse(createResult)
            createdTaskIds.push(created.id)

            const result = await runsListTool.handler(context, { task_id: created.id })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBe(0)
        })
    })

    describe('sandbox-list tool', () => {
        it('should return a paginated list', async () => {
            const result = await sandboxListTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
        })

        it('should respect the limit query parameter', async () => {
            const result = await sandboxListTool.handler(context, { limit: 5, offset: 0 })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.length).toBeLessThanOrEqual(5)
        })
    })

    describe('tasks-runs-retrieve tool', () => {
        // Discovers any existing run in the test project and asserts the retrieve tool
        // path executes cleanly. If no runs exist, the test still passes — verifying at
        // minimum that the discovery call did not error.
        it('should retrieve an existing run when one is available in the project', async () => {
            const tasksResp = parseToolResponse(await listTool.handler(context, { limit: 50 }))
            const tasks: Array<{ id: string }> = tasksResp.results ?? []

            for (const task of tasks) {
                const runsResp = parseToolResponse(await runsListTool.handler(context, { task_id: task.id, limit: 1 }))
                const runs: Array<{ id: string }> = runsResp.results ?? []
                if (runs.length === 0) {
                    continue
                }

                const run = parseToolResponse(
                    await runsRetrieveTool.handler(context, { task_id: task.id, id: runs[0]!.id })
                )
                expect(run.id).toBe(runs[0]!.id)
                expect(run).toHaveProperty('status')
                return
            }
        })
    })

    describe('tasks-runs-session-logs-retrieve tool', () => {
        // Same caveat as tasks-runs-retrieve — discovery-based.
        it('should fetch session logs for an existing run when one is available', async () => {
            const tasksResp = parseToolResponse(await listTool.handler(context, { limit: 50 }))
            const tasks: Array<{ id: string }> = tasksResp.results ?? []

            for (const task of tasks) {
                const runsResp = parseToolResponse(await runsListTool.handler(context, { task_id: task.id, limit: 1 }))
                const runs: Array<{ id: string }> = runsResp.results ?? []
                if (runs.length === 0) {
                    continue
                }

                const logs = parseToolResponse(
                    await runsSessionLogsTool.handler(context, {
                        task_id: task.id,
                        id: runs[0]!.id,
                        limit: 5,
                    })
                )
                // Endpoint shape is { events: [...], next_after?: ... } or paginated;
                // we just assert the call returned an object without throwing.
                expect(logs).toBeTypeOf('object')
                expect(logs).not.toBeNull()
                return
            }
        })
    })

    describe('sandbox-retrieve tool', () => {
        // Sandbox creation is disabled at the MCP level (sandbox-create) and requires
        // an existing environment in the project. Discover one if available and retrieve it.
        it('should retrieve an existing sandbox environment when one is available', async () => {
            const listResp = parseToolResponse(await sandboxListTool.handler(context, { limit: 1 }))
            const sandboxes: Array<{ id: string }> = listResp.results ?? []

            if (sandboxes.length === 0) {
                return
            }

            const sandbox = parseToolResponse(await sandboxRetrieveTool.handler(context, { id: sandboxes[0]!.id }))
            expect(sandbox.id).toBe(sandboxes[0]!.id)
        })
    })

    describe('full CRUD workflow', () => {
        it('should support create → retrieve → update → verify → delete', async () => {
            const title = `CRUD workflow ${generateUniqueKey('crud')}`
            const createResult = await createTool.handler(context, {
                title,
                description: 'CRUD workflow test',
                origin_product: 'user_created' as const,
                repository: 'posthog/posthog',
            })
            const created = parseToolResponse(createResult)
            expect(created.id).toBeTruthy()
            expect(created.title).toBe(title)

            const retrieveResult = await retrieveTool.handler(context, { id: created.id })
            const retrieved = parseToolResponse(retrieveResult)
            expect(retrieved.id).toBe(created.id)
            expect(retrieved.title).toBe(title)

            const newTitle = `Updated CRUD ${generateUniqueKey('crud-upd')}`
            const updateResult = await updateTool.handler(context, {
                id: created.id,
                title: newTitle,
                description: 'Updated CRUD description',
            })
            const updated = parseToolResponse(updateResult)
            expect(updated.title).toBe(newTitle)

            const verifyResult = await retrieveTool.handler(context, { id: created.id })
            const verified = parseToolResponse(verifyResult)
            expect(verified.title).toBe(newTitle)
            expect(verified.description).toBe('Updated CRUD description')

            await deleteTool.handler(context, { id: created.id })

            const listResult = await listTool.handler(context, {})
            const response = parseToolResponse(listResult)
            expect(response.results.some((t: { id: string }) => t.id === created.id)).toBe(false)
        })
    })
})
