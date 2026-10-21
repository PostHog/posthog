import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import { TaskRuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { isLogicRetained, retainMountedLogic } from './retainedLogics'
import { findLiveRunStreamKey, runStreamLogic } from './runStreamLogic'

const PREFETCHED_RUN_STREAMS = 'run-stream-prefetch'
const MAX_PREFETCHED_RUN_STREAMS = 2

export function prefetchRunStream(taskId: string, runId: string, taskRuntime: string | null): void {
    if (!projectLogic.findMounted()?.values.currentProjectId) {
        return
    }
    if (
        taskRuntime === TaskRuntimeEnumApi.Pi &&
        !featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.PI_ACP]
    ) {
        return
    }
    const liveStreamKey = findLiveRunStreamKey(runId)
    if (liveStreamKey !== null) {
        if (liveStreamKey === runId && isLogicRetained(PREFETCHED_RUN_STREAMS, runId)) {
            retainMountedLogic(
                PREFETCHED_RUN_STREAMS,
                runId,
                runStreamLogic({ streamKey: runId }),
                MAX_PREFETCHED_RUN_STREAMS
            )
        }
        return
    }
    const logic = runStreamLogic({ streamKey: runId })
    retainMountedLogic(PREFETCHED_RUN_STREAMS, runId, logic, MAX_PREFETCHED_RUN_STREAMS)
    if (logic.values.bootstrappedRunId === null) {
        logic.actions.bootstrapRun({ taskId, runId, taskRuntime })
    }
}
