import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { LLMTracePerson } from '~/queries/schema/schema-general'

import type { llmPersonsLazyLoaderLogicType } from './llmPersonsLazyLoaderLogicType'

interface PersonAPIResponse {
    uuid: string
    name: string
    distinct_ids: string[]
    properties: Record<string, unknown>
    created_at: string
}

interface BatchByDistinctIdsResponse {
    results: Record<string, PersonAPIResponse>
}

function toTracePerson(apiPerson: PersonAPIResponse, distinctId: string): LLMTracePerson {
    return {
        uuid: apiPerson.uuid,
        created_at: apiPerson.created_at,
        properties: apiPerson.properties,
        distinct_id: distinctId,
    }
}

export const llmPersonsLazyLoaderLogic = kea<llmPersonsLazyLoaderLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmPersonsLazyLoaderLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        ensurePersonLoaded: (distinctId: string) => ({ distinctId }),
        loadPersonsBatchSuccess: (persons: Record<string, LLMTracePerson>, requestedDistinctIds: string[]) => ({
            persons,
            requestedDistinctIds,
        }),
        loadPersonsBatchFailure: (requestedDistinctIds: string[]) => ({ requestedDistinctIds }),
    }),

    reducers({
        personsCache: [
            {} as Record<string, LLMTracePerson | null>,
            {
                loadPersonsBatchSuccess: (state, { persons, requestedDistinctIds }) => {
                    const newState = { ...state }

                    for (const distinctId of requestedDistinctIds) {
                        newState[distinctId] = persons[distinctId] ?? null
                    }

                    return newState
                },
                loadPersonsBatchFailure: (state, { requestedDistinctIds }) => {
                    const newState = { ...state }

                    for (const distinctId of requestedDistinctIds) {
                        newState[distinctId] = null
                    }

                    return newState
                },
            },
        ],

        loadingDistinctIds: [
            new Set<string>(),
            {
                ensurePersonLoaded: (state, { distinctId }) => {
                    if (state.has(distinctId)) {
                        return state
                    }

                    const newSet = new Set(state)
                    newSet.add(distinctId)
                    return newSet
                },
                loadPersonsBatchSuccess: (state, { requestedDistinctIds }) => {
                    const newSet = new Set(state)

                    for (const id of requestedDistinctIds) {
                        newSet.delete(id)
                    }

                    return newSet
                },
                loadPersonsBatchFailure: (state, { requestedDistinctIds }) => {
                    const newSet = new Set(state)

                    for (const id of requestedDistinctIds) {
                        newSet.delete(id)
                    }

                    return newSet
                },
            },
        ],
    }),

    selectors({
        isDistinctIdLoading: [
            (s) => [s.loadingDistinctIds],
            (loadingDistinctIds): ((distinctId: string) => boolean) => {
                return (distinctId: string) => loadingDistinctIds.has(distinctId)
            },
        ],
    }),

    listeners(({ values, actions }) => {
        let pendingDistinctIds = new Set<string>()
        let batchTimer: ReturnType<typeof setTimeout> | null = null

        return {
            ensurePersonLoaded: ({ distinctId }) => {
                if (values.personsCache[distinctId] !== undefined) {
                    return
                }

                pendingDistinctIds.add(distinctId)

                if (batchTimer) {
                    return
                }

                batchTimer = setTimeout(async () => {
                    const batch = Array.from(pendingDistinctIds)
                    pendingDistinctIds = new Set()
                    batchTimer = null

                    if (batch.length === 0) {
                        return
                    }

                    const teamId = values.currentTeamId

                    if (!teamId) {
                        return
                    }

                    try {
                        const response = await api.create<BatchByDistinctIdsResponse>(
                            `api/environments/${teamId}/persons/batch_by_distinct_ids/`,
                            { distinct_ids: batch }
                        )

                        const persons: Record<string, LLMTracePerson> = {}

                        for (const [distinctId, personData] of Object.entries(response.results)) {
                            persons[distinctId] = toTracePerson(personData, distinctId)
                        }

                        actions.loadPersonsBatchSuccess(persons, batch)
                    } catch {
                        actions.loadPersonsBatchFailure(batch)
                    }
                }, 0)
            },
        }
    }),
])
