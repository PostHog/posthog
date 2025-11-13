import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { sessionGroupSummarySceneLogicType } from './sessionGroupSummarySceneLogicType'
import { SessionGroupSummaryType } from './types'

export interface SessionGroupSummarySceneLogicProps {
    id: string
}

export const sessionGroupSummarySceneLogic = kea<sessionGroupSummarySceneLogicType>([
    path(['products', 'session_summaries', 'frontend', 'sessionGroupSummarySceneLogic']),
    props({} as SessionGroupSummarySceneLogicProps),
    key((props) => props.id),

    actions({
        loadSessionGroupSummary: true,
    }),

    reducers({
        accessDeniedToSessionGroupSummary: [
            false,
            {
                loadSessionGroupSummaryFailure: (_, { error }) =>
                    (error as any)?.status === 403 || (error as any)?.statusCode === 403,
            },
        ],
    }),

    loaders(({ props }) => ({
        sessionGroupSummary: [
            null as SessionGroupSummaryType | null,
            {
                loadSessionGroupSummary: async () => {
                    try {
                        return await api.sessionGroupSummaries.get(props.id)
                    } catch (error: any) {
                        if (error.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
            },
        ],
    })),

    selectors({
        sessionGroupSummaryMissing: [
            (s) => [s.sessionGroupSummary, s.sessionGroupSummaryLoading],
            (sessionGroupSummary, sessionGroupSummaryLoading): boolean => {
                return !sessionGroupSummary && !sessionGroupSummaryLoading
            },
        ],
        breadcrumbs: [
            (s) => [s.sessionGroupSummary],
            (sessionGroupSummary): Breadcrumb[] => [
                {
                    key: Scene.SessionGroupSummariesTable,
                    name: 'Session summaries',
                    path: urls.sessionSummaries(),
                },
                {
                    key: Scene.SessionGroupSummary,
                    name: sessionGroupSummary?.title || 'Group summary',
                },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadSessionGroupSummary()
    }),
])
