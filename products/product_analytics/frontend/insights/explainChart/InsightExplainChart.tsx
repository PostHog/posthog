import { useActions, useValues } from 'kea'
import { ExternalLink } from 'lucide-react'
import posthog from 'posthog-js'
import { type ReactNode, useMemo } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'

import type { InsightLogicProps } from '~/types'

import {
    ExplainChartView,
    type StoryEvidenceCharts,
} from 'products/product_analytics/mcp/apps/explainChart/ExplainChartView'

import { ExplainChartEvidenceChart } from './ExplainChartEvidenceChart'
import { ExplainChartFollowUp } from './ExplainChartFollowUp'
import { explainChartLogic } from './explainChartLogic'

const EVIDENCE_CHARTS: StoryEvidenceCharts = {
    canShow: (item) => !!item.chart || !!item.queryTool,
    prefetch: () => {},
    render: (item) => <ExplainChartEvidenceChart item={item} />,
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
        storyEventProperties,
        formatValue,
    } = useValues(explainChartLogic(insightProps))
    const { askFollowUp } = useActions(explainChartLogic(insightProps))
    const evidenceCharts = useMemo<StoryEvidenceCharts>(
        () => ({
            ...EVIDENCE_CHARTS,
            onShow: () => posthog.capture('explain chart evidence chart shown', storyEventProperties),
        }),
        [storyEventProperties]
    )

    if (storyAvailable && storyShown && storyOutdated) {
        return (
            <>
                <LemonBanner type="info" className="m-2">
                    {explainAvailable
                        ? "The explanation is hidden because your changes affect the chart's data. Undo them to see it again, or save and explain this version."
                        : "The explanation is hidden because your changes affect the chart's data. Undo them to see it again."}
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
            <div data-quill>
                <ExplainChartView
                    key={story.headline}
                    data={chartStory}
                    renderChart={(overlay) => <div data-not-quill>{renderChart(overlay)}</div>}
                    openLink={(url) =>
                        window.open(url.startsWith('/') ? addProjectIdIfMissing(url) : url, '_blank', 'noopener')
                    }
                    openLinkLabel={
                        <>
                            Open
                            <ExternalLink className="size-3" />
                        </>
                    }
                    formatValue={formatValue}
                    evidenceCharts={evidenceCharts}
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
                            ...storyEventProperties,
                        })
                    }
                />
            </div>
        </>
    )
}
