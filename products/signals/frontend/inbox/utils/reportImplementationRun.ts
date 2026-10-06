import api from 'lib/api'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { signalsReportArtefactsList } from 'products/signals/frontend/generated/api'

import { TaskRunArtefactContent, deriveTaskPurpose } from '../components/detail/artefactTypes'

// The task↔report association lives in the artefact log, which a report never fills.
const ARTEFACT_FETCH_LIMIT = 1000

/** The task and run a surface opens instead of starting a second implementation. */
export interface ReportImplementationRun {
    taskId: string
    runId: string
}

/**
 * The implementation run still moving on a report, or null when its slot is free. A report holds one
 * implementation at a time, so the server answers a second request with `signal_report_task_cap`. A
 * surface that offers Implement asks this first and opens the run it finds.
 *
 * Ask only when the report says it has an implementation task: the artefact log is read whole before
 * it is paginated, so this is the expensive way to learn there is nothing to open.
 */
export async function findImplementationRunInFlight(
    projectId: string,
    reportId: string
): Promise<ReportImplementationRun | null> {
    const { results } = await signalsReportArtefactsList(projectId, reportId, { limit: ARTEFACT_FETCH_LIMIT })
    const taskIds = new Set<string>()
    for (const artefact of results) {
        if (artefact.type !== 'task_run') {
            continue
        }
        const content = artefact.content as unknown as TaskRunArtefactContent
        if (content?.task_id && deriveTaskPurpose(content)?.purpose === 'implementation') {
            taskIds.add(content.task_id)
        }
    }
    // A task the person can no longer read drops out rather than failing the lookup.
    const tasks = await Promise.all([...taskIds].map((taskId) => api.tasks.get(taskId).catch(() => null)))
    for (const task of tasks) {
        if (task?.latest_run && !isTerminalRunStatus(task.latest_run.status)) {
            return { taskId: task.id, runId: task.latest_run.id }
        }
    }
    return null
}
