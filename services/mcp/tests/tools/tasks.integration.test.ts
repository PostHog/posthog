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
import { GENERATED_TOOLS } from '@/tools/generated/tasks'
import type { Context } from '@/tools/types'

describe('Tasks', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
        cohorts: [],
        tasks: [],
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

    describe('task-create tool', () => {
        const createTool = GENERATED_TOOLS['task-create']!()

        it('should create and run a task by default', async () => {
            const params = {
                title: `MCP Task ${generateUniqueKey('task')}`,
                description: 'Create a task through the generated MCP task tool.',
                origin_product: 'user_created' as const,
                repository: 'posthog/posthog',
            }

            const result = await createTool.handler(context, params)
            const task = parseToolResponse(result)

            expect(task.id).toBeTruthy()
            expect(task.title).toBe(params.title)
            expect(task.description).toBe(params.description)
            expect(task.origin_product).toBe(params.origin_product)
            expect(task.repository).toBe(params.repository)
            expect(task.latest_run?.id).toBeTruthy()
            expect(task._posthogUrl).toContain('/tasks/')

            createdResources.tasks?.push(task.id)
        })

        it('should allow creating without running when run_immediately is false', async () => {
            const result = await createTool.handler(context, {
                title: `MCP Task No Run ${generateUniqueKey('task')}`,
                description: 'Create a task without immediately running it.',
                origin_product: 'user_created' as const,
                run_immediately: false,
            })
            const task = parseToolResponse(result)

            expect(task.id).toBeTruthy()
            expect(task.latest_run).toBeNull()

            createdResources.tasks?.push(task.id)
        })
    })

    describe('tasks-list tool', () => {
        const createTool = GENERATED_TOOLS['task-create']!()
        const listTool = GENERATED_TOOLS['tasks-list']!()

        it('should list tasks and support repository filters', async () => {
            const repository = `posthog/${generateUniqueKey('repo')}`
            const createResult = await createTool.handler(context, {
                title: `List Task ${generateUniqueKey('list')}`,
                description: 'Task used to verify list filters.',
                origin_product: 'user_created' as const,
                repository,
            })
            const createdTask = parseToolResponse(createResult)
            createdResources.tasks?.push(createdTask.id)

            const result = await listTool.handler(context, { repository })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results.some((task: { id: string }) => task.id === createdTask.id)).toBe(true)
            expect(response._posthogUrl).toContain('/tasks')
        })
    })

    describe('task-get tool', () => {
        const createTool = GENERATED_TOOLS['task-create']!()
        const getTool = GENERATED_TOOLS['task-get']!()

        it('should retrieve a task by id', async () => {
            const createResult = await createTool.handler(context, {
                title: `Get Task ${generateUniqueKey('get')}`,
                description: 'Task used to verify retrieval.',
                origin_product: 'user_created' as const,
            })
            const createdTask = parseToolResponse(createResult)
            createdResources.tasks?.push(createdTask.id)

            const result = await getTool.handler(context, { id: createdTask.id })
            const task = parseToolResponse(result)

            expect(task.id).toBe(createdTask.id)
            expect(task.title).toBe(createdTask.title)
            expect(task.description).toBe(createdTask.description)
            expect(task._posthogUrl).toContain(`/tasks/${createdTask.id}`)
        })
    })

    describe('task-runs-list and task-run-get tools', () => {
        const createTool = GENERATED_TOOLS['task-create']!()
        const listRunsTool = GENERATED_TOOLS['task-runs-list']!()
        const getRunTool = GENERATED_TOOLS['task-run-get']!()

        it('should list runs for a task and retrieve a created run', async () => {
            const createResult = await createTool.handler(context, {
                title: `Run Task ${generateUniqueKey('run')}`,
                description: 'Task used to verify run retrieval.',
                origin_product: 'user_created' as const,
            })
            const createdTask = parseToolResponse(createResult)
            createdResources.tasks?.push(createdTask.id)

            const latestRunId = createdTask.latest_run?.id
            expect(latestRunId).toBeTruthy()

            const listResult = await listRunsTool.handler(context, { task_id: createdTask.id })
            const runs = parseToolResponse(listResult)

            expect(Array.isArray(runs.results)).toBe(true)
            expect(runs.results.some((run: { id: string }) => run.id === latestRunId)).toBe(true)

            const getResult = await getRunTool.handler(context, { task_id: createdTask.id, id: latestRunId! })
            const run = parseToolResponse(getResult)

            expect(run.id).toBe(latestRunId)
            expect(run.task).toBe(createdTask.id)
        })
    })

    describe('task-repository-readiness-get tool', () => {
        const readinessTool = GENERATED_TOOLS['task-repository-readiness-get']!()

        it('should return repository readiness details', async () => {
            const result = await readinessTool.handler(context, {
                repository: 'posthog/posthog',
                window_days: 7,
            })
            const readiness = parseToolResponse(result)

            expect(readiness.repository).toBe('posthog/posthog')
            expect(typeof readiness.classification).toBe('string')
            expect(typeof readiness.excluded).toBe('boolean')
            expect(typeof readiness.overall).toBe('string')
            expect(typeof readiness.windowDays).toBe('number')
        })
    })
})
