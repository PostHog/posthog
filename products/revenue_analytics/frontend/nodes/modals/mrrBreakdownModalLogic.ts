import { actions, kea, path, reducers, selectors } from 'kea'

import { RevenueAnalyticsRevenueQueryResultItem } from '~/queries/schema/schema-general'
import { GraphDataset } from '~/types'

import type { mrrBreakdownModalLogicType } from './mrrBreakdownModalLogicType'

export interface MRRBreakdownData {
    labels: string[]
    datasets: {
        new: GraphDataset
        expansion: GraphDataset
        contraction: GraphDataset
        churn: GraphDataset
    }
}

export const mrrBreakdownModalLogic = kea<mrrBreakdownModalLogicType>([
    path(['products', 'revenueAnalytics', 'mrrBreakdownModalLogic']),

    actions({
        openModal: (data: RevenueAnalyticsRevenueQueryResultItem[]) => data,
        closeModal: true,
    }),

    reducers({
        data: [
            null as RevenueAnalyticsRevenueQueryResultItem[] | null,
            {
                openModal: (_, data) => data,
                closeModal: () => null,
            },
        ],
    }),

    selectors({
        isModalOpen: [(s) => [s.data], (data): boolean => !!data],
        newDatasets: [(s) => [s.data], (data): GraphDataset[] => data?.map((item) => item.new as GraphDataset) ?? []],
        expansionDatasets: [
            (s) => [s.data],
            (data): GraphDataset[] => data?.map((item) => item.expansion as GraphDataset) ?? [],
        ],
        contractionDatasets: [
            (s) => [s.data],
            (data): GraphDataset[] => data?.map((item) => item.contraction as GraphDataset) ?? [],
        ],
        churnDatasets: [
            (s) => [s.data],
            (data): GraphDataset[] => data?.map((item) => item.churn as GraphDataset) ?? [],
        ],
    }),
])
