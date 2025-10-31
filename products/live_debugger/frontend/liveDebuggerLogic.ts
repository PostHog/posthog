import { kea, path } from 'kea'

import type { liveDebuggerLogicType } from './liveDebuggerLogicType'

export const liveDebuggerLogic = kea<liveDebuggerLogicType>([
    path(['products', 'live_debugger', 'frontend', 'liveDebuggerLogic']),
])
