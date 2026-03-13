import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import sentimentGenerationsQueryTemplate from '../../backend/queries/sentiment_generations.sql?raw'
import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsSentimentLogicType } from './llmAnalyticsSentimentLogicType'

export type SentimentFilterLabel = 'positive' | 'negative' | 'both'

export interface SentimentGeneration {
    uuid: string
    traceId: string
    aiInput: unknown
    model: string | null
    distinctId: string
    timestamp: string
}

export interface LLMAnalyticsSentimentLogicProps {
    tabId?: string
}

export const llmAnalyticsSentimentLogic = kea<llmAnalyticsSentimentLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsSentimentLogic']),
    key((props: LLMAnalyticsSentimentLogicProps) => props.tabId || 'default'),
    props({} as LLMAnalyticsSentimentLogicProps),
    connect((props: LLMAnalyticsSentimentLogicProps) => ({
        values: [
            llmAnalyticsSharedLogic({ tabId: props.tabId }),
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
    })),

    actions({
        setSentimentFilter: (sentimentFilter: SentimentFilterLabel) => ({ sentimentFilter }),
        setIntensityThreshold: (intensityThreshold: number) => ({ intensityThreshold }),
    }),

    reducers({
        sentimentFilter: [
            'both' as SentimentFilterLabel,
            {
                setSentimentFilter: (_, { sentimentFilter }) => sentimentFilter,
            },
        ],
        intensityThreshold: [
            0.5,
            {
                setIntensityThreshold: (_, { intensityThreshold }) => intensityThreshold,
            },
        ],
    }),

    loaders(({ values }) => ({
        generations: [
            [] as SentimentGeneration[],
            {
                loadGenerations: async () => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: sentimentGenerationsQueryTemplate,
                        filters: {
                            dateRange: {
                                date_from: values.dateFilter.dateFrom || null,
                                date_to: values.dateFilter.dateTo || null,
                            },
                            filterTestAccounts: values.shouldFilterTestAccounts,
                            properties: values.propertyFilters,
                        },
                    })) as HogQLQueryResponse

                    return (response.results || []).map((row) => ({
                        uuid: row[0] as string,
                        traceId: row[1] as string,
                        aiInput: row[2],
                        model: row[3] as string | null,
                        distinctId: row[4] as string,
                        timestamp: row[5] as string,
                    }))
                },
            },
        ],
    })),

    selectors({
        taxonomicGroupTypes: [
            (s) => [s.groupsTaxonomicTypes],
            (groupsTaxonomicTypes: TaxonomicFilterGroupType[]): TaxonomicFilterGroupType[] => [
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                ...groupsTaxonomicTypes,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.HogQLExpression,
            ],
        ],
    }),

    subscriptions(({ actions }) => ({
        dateFilter: () => actions.loadGenerations(),
        shouldFilterTestAccounts: () => actions.loadGenerations(),
        propertyFilters: () => actions.loadGenerations(),
    })),

    afterMount(({ actions }) => {
        actions.loadGenerations()
    }),
])
