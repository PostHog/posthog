import { useValues } from 'kea'

import type { InsightLogicProps } from '~/types'

import { InsightAIAnalysis } from 'products/product_analytics/frontend/insights/shared/InsightAIAnalysis'

import { explainChartLogic } from './explainChartLogic'

export function ExplainChartAIAnalysisFallback({
    insightProps,
}: {
    insightProps: InsightLogicProps
}): JSX.Element | null {
    const { explainAvailable } = useValues(explainChartLogic(insightProps))
    return explainAvailable ? null : <InsightAIAnalysis />
}
