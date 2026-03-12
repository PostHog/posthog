import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import posthog from 'lib/posthog-typed'

import type { exceptionCardLogicType } from './exceptionCardLogicType'

export type ExceptionCardLogicProps = {
    issueId: string
}

export const exceptionCardLogic = kea<exceptionCardLogicType>([
    path((key) => ['products', 'error_tracking', 'ExceptionCard', key]),
    key((props) => props.issueId),
    props({} as ExceptionCardLogicProps),

    actions({
        setShowJSONProperties: (showJSON: boolean) => ({ showJSON }),
        setShowAdditionalProperties: (showProperties: boolean) => ({ showProperties }),
        setShowAsText: (showAsText: boolean) => ({ showAsText }),
        setShowAllFrames: (showAllFrames: boolean) => ({ showAllFrames }),
        setLoading: (loading: boolean) => ({ loading }),
        setCurrentSessionTab: (tab: string) => ({ tab }),
        setCurrentTab: (tab: string) => ({ tab }),
        setFrameExpanded: (rawId: string, expanded: boolean) => ({ rawId, expanded }),
    }),

    reducers({
        expandedFrameRawIds: [
            new Set<string>(),
            {
                setFrameExpanded: (state, { rawId, expanded }) => {
                    const has = state.has(rawId)
                    if (expanded === has) {
                        return state
                    }
                    const next = new Set(state)
                    if (expanded) {
                        next.add(rawId)
                    } else {
                        next.delete(rawId)
                    }
                    return next
                },
            },
        ],
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
            'stack_trace',
            {
                setCurrentTab: (_, { tab }: { tab: string }) => tab,
            },
        ],
    }),

    selectors({
        issueId: [(_, p) => [p.issueId], (issueId) => issueId],
    }),

    listeners(({ props }) => ({
        setFrameExpanded: ({ expanded }) => {
            if (expanded) {
                posthog.capture('error_tracking_stacktrace_explored', { issue_id: props.issueId })
            }
        },
    })),
])
