import { actions, kea, path, reducers, selectors } from 'kea'

import { RevenueAnalyticsMRRQueryResultItem } from '~/queries/schema/schema-general'
import { GraphDataset } from '~/types'

import type { mrrBreakdownModalLogicType } from './mrrBreakdownModalLogicType'

const includeKey =
    (key: `revenue-analytics-${keyof RevenueAnalyticsMRRQueryResultItem}`) => (dataset: GraphDataset) => ({
        ...dataset,
        status: key,
    })

export const mrrBreakdownModalLogic = kea<mrrBreakdownModalLogicType>([
    path(['products', 'revenueAnalytics', 'mrrBreakdownModalLogic']),

    actions({
        openModal: (data: RevenueAnalyticsMRRQueryResultItem[]) => data,
        closeModal: true,
    }),

    reducers({
        data: [
            null as RevenueAnalyticsMRRQueryResultItem[] | null,
            {
                openModal: (_, data) => data,
                closeModal: () => null,
            },
        ],
    }),

    selectors({
        isModalOpen: [(s) => [s.data], (data): boolean => !!data],
        newDatasets: [
            (s) => [s.data],
            (data): GraphDataset[] =>
                (data?.map((item) => item.new as GraphDataset) ?? []).map(includeKey('revenue-analytics-new')),
        ],
        expansionDatasets: [
            (s) => [s.data],
            (data): GraphDataset[] =>
                (data?.map((item) => item.expansion as GraphDataset) ?? []).map(
                    includeKey('revenue-analytics-expansion')
                ),
        ],
        contractionDatasets: [
            (s) => [s.data],
            (data): GraphDataset[] =>
                (data?.map((item) => item.contraction as GraphDataset) ?? []).map(
                    includeKey('revenue-analytics-contraction')
                ),
        ],
        churnDatasets: [
            (s) => [s.data],
            (data): GraphDataset[] =>
                (data?.map((item) => item.churn as GraphDataset) ?? []).map(includeKey('revenue-analytics-churn')),
        ],
    }),
])
