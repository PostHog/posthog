import { MakeLogicType, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { MarketingAnalyticsSearchQuery } from '~/queries/schema/schema-general'

import * as api from '../generated/api'
import { SearchRecommendationsApi } from '../generated/api.schemas'

export interface SearchRecommendationsLogicProps {
    teamId: number | null
    query: MarketingAnalyticsSearchQuery
    goalId: string | null
    enabled: boolean
    refreshKey: string | null
}

export interface searchRecommendationsLogicValues {
    result: SearchRecommendationsApi | null
    resultLoading: boolean
}

export interface searchRecommendationsLogicActions {
    loadRecommendations: () => void
    loadRecommendationsSuccess: (result: SearchRecommendationsApi | null) => { result: SearchRecommendationsApi | null }
    loadRecommendationsFailure: (error: string) => { error: string }
}

export type searchRecommendationsLogicType = MakeLogicType<
    searchRecommendationsLogicValues,
    searchRecommendationsLogicActions,
    SearchRecommendationsLogicProps
>

export const searchRecommendationsLogic = kea<searchRecommendationsLogicType>([
    props({} as SearchRecommendationsLogicProps),
    key((props) => JSON.stringify(props)),
    path((key) => ['products', 'marketingAnalytics', 'searchRecommendationsLogic', key]),
    loaders(({ props }) => ({
        result: [
            null as SearchRecommendationsApi | null,
            {
                loadRecommendations: async (_, breakpoint): Promise<SearchRecommendationsApi | null> => {
                    if (!props.enabled || !props.teamId || !props.query.compareFilter?.compare) {
                        return null
                    }
                    await breakpoint(250)
                    try {
                        const response = await api.marketingAnalyticsSearchRecommendationsCreate(String(props.teamId), {
                            query: {
                                ...props.query,
                                normalizePageUrls:
                                    props.query.normalizePageUrls || props.query.includePostHogConversions,
                            },
                            goal_id: props.goalId,
                        })
                        breakpoint()
                        return response.result
                    } catch {
                        breakpoint()
                        return {
                            recommendations: [],
                            goal_id: props.goalId,
                            warning: 'Could not load suggestions. Try again.',
                        }
                    }
                },
            },
        ],
    })),
    afterMount(({ actions }) => actions.loadRecommendations()),
])
