import { useActions, useValues } from 'kea'
import { ExternalLink } from 'lucide-react'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

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
    const { explainAvailable, story, storyShown, storyVisible, storyOutdated, storySeriesKey, formatValue } = useValues(
        explainChartLogic(insightProps)
    )
    const { askFollowUp } = useActions(explainChartLogic(insightProps))

    if (explainAvailable && storyShown && storyOutdated) {
        return (
            <>
                <LemonBanner type="info" className="m-2">
                    The explanation is hidden because your changes affect the chart's data. Undo them to see it again,
                    or save and explain this version.
                </LemonBanner>
                {renderChart()}
            </>
        )
    }
    if (!explainAvailable || !story || !storyVisible) {
        return <>{renderChart()}</>
    }
    return (
        <div data-quill>
            <ExplainChartView
                key={story.headline}
                data={story}
                renderChart={(overlay) => <div data-not-quill>{renderChart(overlay)}</div>}
                openLink={(url) => window.open(url, '_blank', 'noopener')}
                openLinkLabel={
                    <>
                        Open
                        <ExternalLink className="size-3" />
                    </>
                }
                formatValue={formatValue}
                evidenceCharts={EVIDENCE_CHARTS}
                seriesKey={storySeriesKey ?? undefined}
                chapterAction={(page, step) => <ExplainChartFollowUp onClick={() => askFollowUp(page, step)} />}
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
