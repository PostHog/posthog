import { actions, kea, path, reducers } from 'kea'

import type { fixModalLogicType } from './fixModalLogicType'

export type FixMode = 'explain' | 'fix'

export const fixModalLogic = kea<fixModalLogicType>([
    path(['products', 'error_tracking', 'frontend', 'components', 'ExceptionCard', 'fixModalLogic']),
    actions({
        setMode: (mode: FixMode) => ({ mode }),
    }),
    reducers({
        mode: [
            'fix' as FixMode,
            { persist: true },
            {
                setMode: (_, { mode }) => mode,
            },
        ],
    }),
])
