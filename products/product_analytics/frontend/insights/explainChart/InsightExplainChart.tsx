import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import type { InsightLogicProps } from '~/types'

import { getToolOutputRecord, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'
import {
    ExplainChartView,
    type StoryEvidenceCharts,
} from 'products/product_analytics/mcp/apps/explainChart/ExplainChartView'

import { ExplainChartEvidenceChart } from './ExplainChartEvidenceChart'
import { explainChartLogic } from './explainChartLogic'

const EVIDENCE_CHARTS: StoryEvidenceCharts = {
    canShow: (item) => !!item.chart || !!item.query,
    prefetch: () => {},
    render: (item) => <ExplainChartEvidenceChart item={item} />,
    // pinned: analytics event name, renaming breaks dashboards
    onShow: () => posthog.capture('explain chart evidence chart shown'),
}

export interface InsightExplainChartProps {
    insightProps: InsightLogicProps
    renderChart: (overlay?: ReactNode) => ReactNode
}

/** The chart, with the story PostHog AI told about it beside the chart once the story is in. */
export function InsightExplainChart({ insightProps, renderChart }: InsightExplainChartProps): JSX.Element {
    const { explainAvailable, story, storyShown, formatValue } = useValues(explainChartLogic(insightProps))
    const { explainChartToolCompleted } = useActions(explainChartLogic(insightProps))

    useMcpToolApplyBack({
        tools: ['explain-chart'],
        targetKey: `explain-chart-${keyForInsightLogicProps('new')(insightProps)}`,
        active: explainAvailable,
        onApply: (event, { innerInput }) =>
            explainChartToolCompleted(
                innerInput,
                getToolOutputRecord({ rawOutput: event.invocation.output, status: event.invocation.status })
            ),
    })

    if (!explainAvailable || !story || !storyShown) {
        return <>{renderChart()}</>
    }
    // The explanation is a quill view, so it takes quill's colors. The charts inside it keep PostHog's.
    return (
        <div data-quill>
            <ExplainChartView
                // A new story starts at its summary.
                key={story.headline}
                data={story}
                renderChart={(overlay) => <div data-not-quill>{renderChart(overlay)}</div>}
                openLink={(url) => window.open(url, '_blank', 'noopener')}
                formatValue={formatValue}
                evidenceCharts={EVIDENCE_CHARTS}
                onPageChange={({ index, fromIndex, source }) =>
                    // pinned: analytics event name, renaming breaks dashboards
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
