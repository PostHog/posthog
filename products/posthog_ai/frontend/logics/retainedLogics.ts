import { BuiltLogic, getContext } from 'kea'

import { findLiveRunStreamKey } from './runStreamLogic'

export const RETAINED_RUN_STREAMS = 'run-stream'

const retainedByContext = new WeakMap<object, Map<string, Map<string, () => void>>>()

function retainedGroup(group: string): Map<string, () => void> {
    const context = getContext()
    let groups = retainedByContext.get(context)
    if (!groups) {
        groups = new Map()
        retainedByContext.set(context, groups)
    }
    let retained = groups.get(group)
    if (!retained) {
        retained = new Map()
        groups.set(group, retained)
    }
    return retained
}

export function retainMountedLogic(group: string, key: string, logic: BuiltLogic, limit: number): boolean {
    const retained = retainedGroup(group)
    const unmount = retained.get(key)
    if (unmount) {
        retained.delete(key)
        retained.set(key, unmount)
        return true
    }
    retained.set(key, logic.mount())
    for (const [oldestKey, oldestUnmount] of retained) {
        if (retained.size <= limit) {
            break
        }
        retained.delete(oldestKey)
        oldestUnmount()
    }
    return false
}

export function isLogicRetained(group: string, key: string): boolean {
    return retainedGroup(group).has(key)
}

export function resolveRunStreamKey(runId: string, streamKey: string | undefined): string | undefined {
    if (streamKey && streamKey !== runId) {
        return streamKey
    }
    return findLiveRunStreamKey(runId) ?? streamKey
}
