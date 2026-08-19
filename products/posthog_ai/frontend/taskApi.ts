import api, { ApiConfig, PaginatedResponse } from 'lib/api'

import {
    getTasksRunsStreamRetrieveUrl,
    tasksCreate,
    tasksDestroy,
    tasksList,
    tasksRepositoriesRetrieve,
    tasksRetrieve,
    tasksRunCreate,
    tasksRunsList,
    tasksRunsLogsRetrieve,
    tasksRunsRetrieve,
    tasksUpdate,
} from 'products/tasks/frontend/generated/api'

import { Task, TaskListParams, TaskRun, TaskUpsertProps } from './types/taskTypes'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export const taskApi = {
    async list(params: TaskListParams = {}): Promise<PaginatedResponse<Task>> {
        return (await tasksList(
            projectId(),
            params as Parameters<typeof tasksList>[1]
        )) as unknown as PaginatedResponse<Task>
    },
    async repositories(): Promise<{ repositories: string[] }> {
        return await tasksRepositoriesRetrieve(projectId())
    },
    async get(id: string, params: { ph_debug?: boolean | 'true' } = {}): Promise<Task> {
        return (await tasksRetrieve(projectId(), id, params as Parameters<typeof tasksRetrieve>[2])) as unknown as Task
    },
    async create(data: TaskUpsertProps): Promise<Task> {
        return (await tasksCreate(projectId(), data as Parameters<typeof tasksCreate>[1])) as unknown as Task
    },
    async update(id: string, data: Partial<TaskUpsertProps>): Promise<Task> {
        return (await tasksUpdate(projectId(), id, data as Parameters<typeof tasksUpdate>[2])) as unknown as Task
    },
    async delete(id: string): Promise<void> {
        await tasksDestroy(projectId(), id)
    },
    async run(id: string, data?: Parameters<typeof tasksRunCreate>[2]): Promise<Task> {
        return (await tasksRunCreate(projectId(), id, data)) as unknown as Task
    },
    runs: {
        async list(taskId: string, params: Record<string, any> = {}): Promise<PaginatedResponse<TaskRun>> {
            return (await tasksRunsList(
                projectId(),
                taskId,
                params as Parameters<typeof tasksRunsList>[2]
            )) as unknown as PaginatedResponse<TaskRun>
        },
        async get(taskId: string, runId: string, params: { ph_debug?: boolean | 'true' } = {}): Promise<TaskRun> {
            return (await tasksRunsRetrieve(
                projectId(),
                taskId,
                runId,
                params as Parameters<typeof tasksRunsRetrieve>[3]
            )) as unknown as TaskRun
        },
        async getLogEntries(taskId: string, runId: string): Promise<Record<string, any>[]> {
            const text = await tasksRunsLogsRetrieve(projectId(), taskId, runId)
            const entries: Record<string, any>[] = []
            for (const line of text.split('\n')) {
                try {
                    if (line.trim()) {
                        entries.push(JSON.parse(line))
                    }
                } catch {
                    // Historical replay is best-effort when a stored line is malformed.
                }
            }
            return entries
        },
        async openStream(
            taskId: string,
            runId: string,
            options: {
                signal: AbortSignal
                lastEventId?: string
                startLatest?: boolean
                proxyTarget?: { baseUrl: string; token: string }
            }
        ): Promise<Response> {
            const headers: Record<string, string> = {}
            if (options.lastEventId) {
                headers['Last-Event-ID'] = options.lastEventId
            }
            if (options.proxyTarget) {
                const base = options.proxyTarget.baseUrl.replace(/\/+$/, '')
                const url =
                    !options.lastEventId && options.startLatest
                        ? `${base}/v1/runs/${runId}/stream?start=latest`
                        : `${base}/v1/runs/${runId}/stream`
                headers.Authorization = `Bearer ${options.proxyTarget.token}`
                return api.getResponse(url, { signal: options.signal, headers })
            }
            const url = getTasksRunsStreamRetrieveUrl(
                projectId(),
                taskId,
                runId,
                !options.lastEventId && options.startLatest ? { start: 'latest' } : undefined
            )
            return api.getResponse(url, { signal: options.signal, headers })
        },
    },
}
