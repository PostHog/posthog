import { ApiError, apiJson } from '@/api/client'

import type { TaskLookup } from './notificationRouting'

interface TaskReportApi {
    signal_report?: string | null
}

export async function findTask(projectId: number, taskId: string): Promise<TaskLookup> {
    try {
        const task = await apiJson<TaskReportApi>(`/api/projects/${projectId}/tasks/${encodeURIComponent(taskId)}/`)
        return { found: true, reportId: task.signal_report ?? null }
    } catch (error) {
        if (error instanceof ApiError && (error.status === 404 || error.status === 403)) {
            return { found: false }
        }
        throw error
    }
}
