import type { InsightVizNode } from '~/queries/schema/schema-general'
import type { FunnelStep, TrendResult } from '~/types'

export type ResultBreakdownRenderProps = {
    query: InsightVizNode | null
    breakdownResultsLoading: boolean
    breakdownResults: FunnelStep[] | FunnelStep[][] | TrendResult[] | null
    exposureDifference: number
    breakdownLastRefresh: string | null
}
