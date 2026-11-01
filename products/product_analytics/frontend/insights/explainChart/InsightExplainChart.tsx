import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'

import type { InsightLogicProps } from '~/types'

import {
    ExplainChartView,
    type StoryEvidenceCharts,
} from 'products/product_analytics/mcp/apps/explainChart/ExplainChartView'

import { ExplainChartEvidenceChart } from './ExplainChartEvidenceChart'
import { ExplainChartFollowUp } from './ExplainChartFollowUp'
import { explainChartLogic } from './explainChartLogic'

const EVIDENCE_CHARTS: StoryEvidenceCharts = {
    canShow: (item) => !!item.chart || !!item.query,
    prefetch: () => {},
    render: (item) => <ExplainChartEvidenceChart item={item} />,
    onShow: () => posthog.capture('explain chart evidence chart shown'),
}

export interface InsightExplainChartProps {
    insightProps: InsightLogicProps
    renderChart: (overlay?: ReactNode) => ReactNode
}

export function InsightExplainChart({ insightProps, renderChart }: InsightExplainChartProps): JSX.Element {
    const { storyAvailable, explainAvailable, story, chartStory, storyShown, storySeriesKey, formatValue } = useValues(
        explainChartLogic(insightProps)
    )
    const { askFollowUp } = useActions(explainChartLogic(insightProps))

    if (!storyAvailable || !story || !chartStory || !storyShown) {
        return <>{renderChart()}</>
    }
    return (
        <div data-quill>
            <ExplainChartView
                key={story.headline}
                data={chartStory}
                renderChart={(overlay) => <div data-not-quill>{renderChart(overlay)}</div>}
                openLink={(url) => window.open(url, '_blank', 'noopener')}
                formatValue={formatValue}
                evidenceCharts={EVIDENCE_CHARTS}
                seriesKey={storySeriesKey ?? undefined}
                chapterAction={
                    explainAvailable
                        ? (page, step) => <ExplainChartFollowUp onClick={() => askFollowUp(page, step)} />
                        : undefined
                }
                onPageChange={({ index, fromIndex, source }) =>
                    posthog.capture('explain chart page viewed', {
                        page_index: index,
                        from_page_index: fromIndex,
                        page_count: story.chapters.length + 1,
                        source,
                    })
                }
            />
        </div>
    )
}
