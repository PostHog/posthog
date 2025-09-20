import { actions, kea, path, reducers } from 'kea'

import type { exceptionCardLogicType } from './exceptionCardLogicType'

export const exceptionCardLogic = kea<exceptionCardLogicType>([
    path(() => ['products', 'error_tracking', 'components', 'ExceptionCard', 'exceptionCardLogic']),

    actions({
        setShowJSONProperties: (showJSON: boolean) => ({ showJSON }),
        setShowAdditionalProperties: (showProperties: boolean) => ({ showProperties }),
        setShowAsText: (showAsText: boolean) => ({ showAsText }),
        setShowAllFrames: (showAllFrames: boolean) => ({ showAllFrames }),
        setLoading: (loading: boolean) => ({ loading }),
        setCurrentSessionTab: (tab: string) => ({ tab }),
        setCurrentTab: (tab: string) => ({ tab }),
    }),

    reducers({
        showJSONProperties: [
            false,
            {
                setShowJSONProperties: (_, { showJSON }) => showJSON,
            },
        ],
        showAdditionalProperties: [
            true,
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
        currentSessionTab: [
            'timeline',
            {
                setCurrentSessionTab: (_, { tab }: { tab: string }) => tab,
            },
        ],
        currentTab: [
            'stacktrace',
            {
                setCurrentTab: (_, { tab }: { tab: string }) => tab,
            },
        ],
    }),
])
