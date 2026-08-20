import { describe, expect, it, vi } from 'vitest'

import { tasksContextToolsToExclude } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'
import {
    TASKS_CONTEXT_TOOL_NAMES,
    tasksArtifactsList,
    tasksCommentsList,
    tasksCommentsRetrieve,
} from '@/tools/tasksContext'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

function context(taskId: string | undefined): {
    context: Context
    request: ReturnType<typeof vi.fn>
} {
    const request = vi.fn().mockResolvedValue({})
    return {
        request,
        context: {
            api: { config: { taskId }, request },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
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
