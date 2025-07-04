import { actions, kea, path, reducers } from 'kea'

import type { exceptionCardLogicType } from './exceptionCardLogicType'

export const exceptionCardLogic = kea<exceptionCardLogicType>([
    path(() => ['scenes', 'error-tracking', 'exceptionCardLogic']),

    actions({
        setShowJSONProperties: (showJSON: boolean) => ({ showJSON }),
        setShowAdditionalProperties: (showProperties: boolean) => ({ showProperties }),
        setShowAsText: (showAsText: boolean) => ({ showAsText }),
        setShowAllFrames: (showAllFrames: boolean) => ({ showAllFrames }),
        setLoading: (loading: boolean) => ({ loading }),
    }),

    reducers({
        showJSONProperties: [
            false,
            {
                setShowJSONProperties: (_, { showJSON }) => showJSON,
            },
        ],
        showAdditionalProperties: [
            false,
            {
                setShowAdditionalProperties: (_, { showProperties }) => showProperties,
            },
        ],
        showAsText: [
            false,
            {
                setShowAsText: (_, { showAsText }) => showAsText,
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
    }),
])
