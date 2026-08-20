import { describe, expect, it, vi } from 'vitest'

import { tasksContextToolsToExclude } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'
import {
    TASKS_CONTEXT_TOOL_NAMES,
    tasksArtifactsList,
    tasksCommentsList,
    tasksCommentsRetrieve,
    tasksCurrentRetrieve,
    tasksMineList,
} from '@/tools/tasksContext'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

function context(
    taskId: string | undefined,
    options: { userId?: number; response?: unknown } = {}
): {
    context: Context
    request: ReturnType<typeof vi.fn>
} {
    const request = vi.fn().mockResolvedValue(options.response ?? {})
    return {
        request,
        context: {
            api: {
                config: { taskId },
                request,
                getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/42'),
            },
            stateManager: {
                getProjectId: vi.fn().mockResolvedValue('42'),
                getUser: vi.fn().mockResolvedValue({ id: options.userId, distinct_id: 'd1', email: 'a@b.c' }),
            },
        } as unknown as Context,
    }
}

describe('task artifacts and comments tools', () => {
    it('uses the resource scopes required by the backing endpoints', () => {
        const definitions = getToolDefinitions()
        expect(definitions['tasks-artifacts-list']?.required_scopes).toEqual(['task:read'])
        expect(definitions['tasks-comments-list']?.required_scopes).toEqual(['comment:read'])
        expect(definitions['tasks-comments-retrieve']?.required_scopes).toEqual(['comment:read'])
    })

    it('advertises them only to a stamped PostHog Desktop task', () => {
        const code = new MCPClientProfile({ consumer: 'posthog-code' })
        expect(tasksContextToolsToExclude(code, 'task-1')).toEqual([])
        expect(tasksContextToolsToExclude(code, undefined)).toEqual(TASKS_CONTEXT_TOOL_NAMES)
        expect(tasksContextToolsToExclude(new MCPClientProfile({ consumer: 'other' }), 'task-1')).toEqual(
            TASKS_CONTEXT_TOOL_NAMES
        )
    })

    it('calls the task-bound endpoint without accepting a task id', async () => {
        const { context: toolContext, request } = context('task-host-stamped')

        await tasksArtifactsList().handler(toolContext, {})
        await tasksCommentsList().handler(toolContext, {
            artifact_id: 'artifact-a',
            include_resolved: true,
            limit: 25,
            cursor: 'next-page',
        })
        await tasksCommentsRetrieve().handler(toolContext, {
            root_comment_id: '019fcdb5-2e5b-7ab1-bdab-b77fafd3c96f',
            limit: 20,
            cursor: 'reply-page',
        })

        expect(request.mock.calls).toEqual([
            [
                {
                    method: 'GET',
                    path: '/api/projects/42/tasks/task-host-stamped/artifacts/',
                    query: undefined,
                },
            ],
            [
                {
                    method: 'GET',
                    path: '/api/projects/42/tasks/task-host-stamped/comments/',
                    query: {
                        artifact_id: 'artifact-a',
                        include_resolved: true,
                        limit: 25,
                        cursor: 'next-page',
                    },
                },
            ],
            [
                {
                    method: 'GET',
                    path: '/api/projects/42/tasks/task-host-stamped/comments/019fcdb5-2e5b-7ab1-bdab-b77fafd3c96f/',
                    query: { limit: 20, cursor: 'reply-page' },
                },
            ],
        ])
    })

    it('fails closed when the host did not stamp a task', async () => {
        const { context: toolContext, request } = context(undefined)

        await expect(tasksArtifactsList().handler(toolContext, {})).rejects.toThrow('current PostHog Desktop task')
        expect(request).not.toHaveBeenCalled()
    })
})

describe('tasks-current-retrieve', () => {
    it('uses task:read and is gated on the stamped task id', () => {
        const definitions = getToolDefinitions()
        expect(definitions['tasks-current-retrieve']?.required_scopes).toEqual(['task:read'])
        expect(TASKS_CONTEXT_TOOL_NAMES).toContain('tasks-current-retrieve')
    })

    it('retrieves the host-stamped task', async () => {
        const { context: toolContext, request } = context('task-host-stamped', {
            response: { id: 'task-host-stamped', title: 'T' },
        })

        const result = await tasksCurrentRetrieve().handler(toolContext, {})

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/tasks/task-host-stamped/',
        })
        expect(result).toMatchObject({
            id: 'task-host-stamped',
            _posthogUrl: 'https://us.posthog.com/project/42/tasks/task-host-stamped',
        })
    })

    it('strips sandbox credentials from the latest run', async () => {
        const { context: toolContext } = context('task-host-stamped', {
            response: {
                id: 'task-host-stamped',
                latest_run: {
                    status: 'in_progress',
                    log_url: 'https://s3/presigned',
                    state: { sandbox_connect_token: 'secret', sandbox_url: 'https://sandbox', stage: 'build' },
                },
            },
        })

        const result = (await tasksCurrentRetrieve().handler(toolContext, {})) as Record<string, any>

        expect(result.latest_run.status).toBe('in_progress')
        expect(result.latest_run.log_url).toBeUndefined()
        expect(result.latest_run.state.sandbox_connect_token).toBeUndefined()
        expect(result.latest_run.state.sandbox_url).toBeUndefined()
    })

    it('fails closed when the host did not stamp a task', async () => {
        const { context: toolContext, request } = context(undefined)

        await expect(tasksCurrentRetrieve().handler(toolContext, {})).rejects.toThrow('running task session')
        expect(request).not.toHaveBeenCalled()
    })
})

describe('tasks-mine-list', () => {
    const taskPage = {
        count: 2,
        next: null,
        previous: null,
        results: [
            {
                id: 'task-current',
                title: 'Current',
                latest_run: { id: 'run-1', status: 'in_progress', environment: 'local', log_url: 'https://s3' },
            },
            {
                id: 'task-other',
                title: 'Other',
                latest_run: { id: 'run-2', status: 'completed', environment: 'cloud' },
            },
        ],
    }

    it('uses task:read and is not gated on the stamped task id', () => {
        const definitions = getToolDefinitions()
        expect(definitions['tasks-mine-list']?.required_scopes).toEqual(['task:read'])
        expect(TASKS_CONTEXT_TOOL_NAMES).not.toContain('tasks-mine-list')
    })

    it('resolves created_by from the calling user and marks the current task', async () => {
        const { context: toolContext, request } = context('task-current', { userId: 7, response: taskPage })

        const result = (await tasksMineList().handler(toolContext, { status: 'in_progress', limit: 10 } as any)) as any

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/tasks/',
            query: expect.objectContaining({ created_by: 7, status: 'in_progress', limit: 10 }),
        })
        expect(result.results[0]).toMatchObject({
            id: 'task-current',
            is_current_task: true,
            latest_run: { status: 'in_progress', environment: 'local' },
        })
        expect(result.results[0].latest_run.log_url).toBeUndefined()
        expect(result.results[1].is_current_task).toBeUndefined()
        expect(result.results[1].latest_run.environment).toBe('cloud')
    })

    it('works outside a task session without marking anything current', async () => {
        const { context: toolContext } = context(undefined, { userId: 7, response: taskPage })

        const result = (await tasksMineList().handler(toolContext, {} as any)) as any

        expect(result.results.every((r: any) => r.is_current_task === undefined)).toBe(true)
    })

    it('fails when the user id cannot be resolved', async () => {
        const { context: toolContext, request } = context(undefined, { response: taskPage })

        await expect(tasksMineList().handler(toolContext, {} as any)).rejects.toThrow('user id')
        expect(request).not.toHaveBeenCalled()
    })
})
