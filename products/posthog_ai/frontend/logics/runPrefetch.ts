import { projectLogic } from 'scenes/projectLogic'

import { retainMountedLogic } from './retainedLogics'
import { runStreamLogic } from './runStreamLogic'

const PREFETCHED_RUN_STREAMS = 'run-stream-prefetch'
const MAX_PREFETCHED_RUN_STREAMS = 2

export function prefetchRunStream(taskId: string, runId: string, taskRuntime: string | null): void {
    if (!projectLogic.findMounted()?.values.currentProjectId) {
        return
    }
    const logic = runStreamLogic({ streamKey: runId })
    retainMountedLogic(PREFETCHED_RUN_STREAMS, runId, logic, MAX_PREFETCHED_RUN_STREAMS)
    if (logic.values.bootstrappedRunId !== runId) {
        logic.actions.bootstrapRun({ taskId, runId, taskRuntime })
    }
}
