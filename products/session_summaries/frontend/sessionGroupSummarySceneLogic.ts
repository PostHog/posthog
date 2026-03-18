import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { sessionGroupSummarySceneLogicType } from './sessionGroupSummarySceneLogicType'
import {
    EnrichedSessionGroupSummaryPatternsList,
    PatternAssignedEventSegmentContext,
    SessionGroupSummaryType,
} from './types'

export interface SessionGroupSummarySceneLogicProps {
    id: string
}

export const sessionGroupSummarySceneLogic = kea<sessionGroupSummarySceneLogicType>([
    path(['products', 'session_summaries', 'frontend', 'sessionGroupSummarySceneLogic']),
    props({} as SessionGroupSummarySceneLogicProps),
    key((props) => props.id),

    actions({
        loadSessionGroupSummary: true,
        openSessionDetails: (patternId: number, targetEventUuid: string) => ({ patternId, targetEventUuid }),
        closeSessionDetails: true,
    }),

    reducers({
        accessDeniedToSessionGroupSummary: [
            false,
            {
                loadSessionGroupSummaryFailure: (_, { error }) =>
                    (error as any)?.status === 403 || (error as any)?.statusCode === 403,
            },
        ],
        selectedPatternId: [
            null as number | null,
            {
                openSessionDetails: (_, { patternId }) => patternId,
                closeSessionDetails: () => null,
            },
        ],
        selectedEventUuid: [
            null as string | null,
            {
                openSessionDetails: (_, { targetEventUuid }) => targetEventUuid,
                closeSessionDetails: () => null,
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
        selectedEvent: [
            (s) => [s.sessionGroupSummary, s.selectedPatternId, s.selectedEventUuid],
            (sessionGroupSummary, selectedPatternId, selectedEventUuid): PatternAssignedEventSegmentContext | null => {
                if (!sessionGroupSummary || selectedPatternId === null || !selectedEventUuid) {
                    return null
                }
                const summary = JSON.parse(
                    sessionGroupSummary.summary || '{}'
                ) as EnrichedSessionGroupSummaryPatternsList
                const pattern = summary.patterns?.find((p) => p.pattern_id === selectedPatternId)
                if (!pattern) {
                    return null
                }
                return pattern.events.find((e) => e.target_event.event_uuid === selectedEventUuid) || null
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

    actionToUrl(({ values }) => {
        const buildURL = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            const hashParams: Record<string, any> = { ...router.values.hashParams }

            if (values.selectedPatternId !== null && values.selectedEventUuid) {
                hashParams.patternId = values.selectedPatternId
                hashParams.targetEventId = values.selectedEventUuid
            } else {
                delete hashParams.patternId
                delete hashParams.targetEventId
            }

            return [router.values.location.pathname, router.values.searchParams, hashParams, { replace: true }]
        }

        return {
            openSessionDetails: () => buildURL(),
            closeSessionDetails: () => buildURL(),
        }
    }),

    urlToAction(({ actions, values }) => ({
        '*': (_: any, _searchParams: any, hashParams: Record<string, any>) => {
            const patternId = hashParams.patternId ? Number(hashParams.patternId) : null
            const targetEventId = hashParams.targetEventId || null

            if (
                patternId !== null &&
                targetEventId &&
                (values.selectedEventUuid !== targetEventId || values.selectedPatternId !== patternId)
            ) {
                actions.openSessionDetails(patternId, targetEventId)
            } else if (!patternId && !targetEventId && values.selectedEventUuid) {
                actions.closeSessionDetails()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSessionGroupSummary()
    }),
])
