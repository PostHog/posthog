import api from 'lib/api'

import { signalsReportArtefactsList } from 'products/signals/frontend/generated/api'

import { deriveTaskPurpose, TaskRunArtefactContent } from '../components/detail/artefactTypes'
import { SignalReport, SignalReportArtefact } from '../types'

export interface ImplementationRunRef {
    taskId: string
    runId: string
}

// A report logs a few runs at most, so one page covers its run history.
const ARTEFACT_PAGE_SIZE = 200

export function latestImplementationRunRef(artefacts: SignalReportArtefact[]): ImplementationRunRef | null {
    let latest: { ref: ImplementationRunRef; at: string } | null = null
    for (const artefact of artefacts) {
        if (artefact.type !== 'task_run') {
            continue
        }
        const content = artefact.content as TaskRunArtefactContent
        if (!content?.task_id || !content.run_id || deriveTaskPurpose(content)?.purpose !== 'implementation') {
            continue
        }
        if (!latest || artefact.created_at > latest.at) {
            latest = { ref: { taskId: content.task_id, runId: content.run_id }, at: artefact.created_at }
        }
    }
    return latest?.ref ?? null
}

/** The list row carries no run ids, so this asks the server: the task claim first, then the run log. */
export async function findLatestImplementationRun(
    projectId: string,
    report: Pick<SignalReport, 'id' | 'assignee'>
): Promise<ImplementationRunRef | null> {
    const claimedTaskId = report.assignee?.kind === 'task' ? report.assignee.task_id : null
    if (claimedTaskId) {
        const task = await api.tasks.get(claimedTaskId)
        if (task.latest_run?.id) {
            return { taskId: task.id, runId: task.latest_run.id }
        }
    }
    const response = await signalsReportArtefactsList(projectId, report.id, { limit: ARTEFACT_PAGE_SIZE })
    return latestImplementationRunRef(response.results as SignalReportArtefact[])
}
