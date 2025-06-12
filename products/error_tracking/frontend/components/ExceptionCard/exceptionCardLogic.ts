import { actions, kea, path, reducers } from 'kea'

import type { exceptionCardLogicType } from './exceptionCardLogicType'

export const exceptionCardLogic = kea<exceptionCardLogicType>([
    path(() => ['scenes', 'error-tracking', 'exceptionCardLogic']),

    actions({
        setShowAsText: (showAsText: boolean) => ({ showAsText }),
        setShowAllFrames: (showAllFrames: boolean) => ({ showAllFrames }),
        setLoading: (loading: boolean) => ({ loading }),
        setShowFixModal: (showFixModal: boolean) => ({ showFixModal }),
    }),

    reducers({
        showAsText: [
            false,
            {
                setShowAsText: (_, { showAsText }: { showAsText: boolean }) => showAsText,
            },
        ],
        showAllFrames: [
            false,
            {
                setShowAllFrames: (_, { showAllFrames }: { showAllFrames: boolean }) => showAllFrames,
            },
        ],
        loading: [
            true,
            {
                setLoading: (_, { loading }: { loading: boolean }) => loading,
            },
        ],
        showFixModal: [
            false,
            {
                setShowFixModal: (_, { showFixModal }: { showFixModal: boolean }) => showFixModal,
            },
        ],
    }),
])
