import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { tasksSlackThreadContextRetrieve } from 'products/tasks/frontend/generated/api'
import { SlackThreadContextResponseApi } from 'products/tasks/frontend/generated/api.schemas'

import type { slackTaskContextSceneLogicType } from './slackTaskContextSceneLogicType'

export type SlackTaskContextSubmissionError = {
    status: number | null
    detail: string
}

export const slackTaskContextSceneLogic = kea<slackTaskContextSceneLogicType>([
    path(['products', 'tasks', 'frontend', 'logics', 'slackTaskContextSceneLogic']),

    actions({
        setUrl: (url: string) => ({ url }),
        clearResult: true,
        setSubmissionError: (error: SlackTaskContextSubmissionError | null) => ({ error }),
    }),

    reducers({
        url: [
            '' as string,
            {
                setUrl: (_, { url }) => url,
                clearResult: () => '',
            },
        ],
        submissionError: [
            null as SlackTaskContextSubmissionError | null,
            {
                setSubmissionError: (_, { error }) => error,
                setUrl: () => null,
                clearResult: () => null,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        result: [
            null as SlackThreadContextResponseApi | null,
            {
                loadResult: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (teamId == null) {
                        actions.setSubmissionError({ status: null, detail: 'No active team.' })
                        return null
                    }
                    const trimmed = values.url.trim()
                    if (!trimmed) {
                        actions.setSubmissionError({ status: null, detail: 'Enter a Slack thread URL.' })
                        return null
                    }
                    actions.setSubmissionError(null)
                    try {
                        return await tasksSlackThreadContextRetrieve(String(teamId), { url: trimmed })
                    } catch (e: any) {
                        const status: number | null =
                            typeof e?.status === 'number'
                                ? e.status
                                : typeof e?.response?.status === 'number'
                                  ? e.response.status
                                  : null
                        const detail: string =
                            e?.data?.detail ?? e?.response?.data?.detail ?? e?.message ?? 'Request failed.'
                        actions.setSubmissionError({ status, detail })
                        return null
                    }
                },
                clearResult: () => null,
            },
        ],
    })),

    selectors({
        canSubmit: [(s) => [s.url, s.resultLoading], (url, loading): boolean => url.trim().length > 0 && !loading],
    }),
])
