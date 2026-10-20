import { BuiltLogic, getContext } from 'kea'

export const RETAINED_RUN_STREAMS = 'run-stream'

interface RetainedLogic {
    logic: BuiltLogic
    unmount: () => void
}

const retainedByContext = new WeakMap<object, Map<string, Map<string, RetainedLogic>>>()

function retainedGroup(group: string): Map<string, RetainedLogic> {
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
    const existing = retained.get(key)
    if (existing) {
        retained.delete(key)
        retained.set(key, existing)
        return true
    }
    retained.set(key, { logic, unmount: logic.mount() })
    for (const [oldestKey, oldest] of retained) {
        if (retained.size <= limit) {
            break
        }
        retained.delete(oldestKey)
        oldest.unmount()
    }
    return false
}

export function isLogicRetained(group: string, key: string): boolean {
    return retainedGroup(group).has(key)
}

export function findRetainedLogicKey(group: string, matches: (logic: BuiltLogic) => boolean): string | null {
    for (const [key, { logic }] of retainedGroup(group)) {
        if (matches(logic)) {
            return key
        }
    }
    return null
}
