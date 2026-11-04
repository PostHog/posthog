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

import { ExplainChartByline } from './ExplainChartByline'
import { ExplainChartEvidenceChart } from './ExplainChartEvidenceChart'
import { ExplainChartFollowUp } from './ExplainChartFollowUp'
import { explainChartLogic } from './explainChartLogic'

const EVIDENCE_CHARTS: StoryEvidenceCharts = {
    canShow: (item) => !!item.chart || !!item.queryTool,
    prefetch: () => {},
    render: (item) => <ExplainChartEvidenceChart item={item} />,
    onShow: () => posthog.capture('explain chart evidence chart shown'),
}

export interface InsightExplainChartProps {
    insightProps: InsightLogicProps
    renderChart: (overlay?: ReactNode) => ReactNode
}

export function InsightExplainChart({ insightProps, renderChart }: InsightExplainChartProps): JSX.Element {
    const {
        storyAvailable,
        explainAvailable,
        story,
        chartStory,
        storyShown,
        storyVisible,
        storyOutdated,
        storySeriesKey,
        storyAuthor,
        formatValue,
    } = useValues(explainChartLogic(insightProps))
    const { askFollowUp } = useActions(explainChartLogic(insightProps))

    if (storyAvailable && storyShown && storyOutdated) {
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
    if (!storyAvailable || !story || !chartStory || !storyVisible) {
        return <>{renderChart()}</>
    }
    return (
        <>
            {storyAuthor && <ExplainChartByline author={storyAuthor} />}
            <div data-quill>
                <ExplainChartView
                    key={story.headline}
                    data={chartStory}
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
        </>
    )
}
