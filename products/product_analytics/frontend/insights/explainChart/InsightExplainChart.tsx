import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { type ReactNode, useMemo } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { Query } from '~/queries/Query/Query'
import type { InsightVizNode } from '~/queries/schema/schema-general'
import type { InsightLogicProps, TrendResult } from '~/types'

import {
    ExplainChartView,
    type StoryEvidenceCharts,
} from 'products/product_analytics/mcp/apps/explainChart/ExplainChartView'
import { isSeriesNamedIn } from 'products/product_analytics/mcp/apps/explainChart/storyNamedSeries'

import { explainChartLogic } from './explainChartLogic'
import { ExplainChartLookDeeper } from './ExplainChartLookDeeper'

function seriesNames(result: TrendResult): string[] {
    return [result.label ?? '', ...[result.breakdown_value ?? []].flat().map(String)]
}

// An evidence chart applies the same dashboard filters and variables as the chart it explains.
function evidenceCharts(
    filtersOverride: InsightLogicProps['filtersOverride'],
    variablesOverride: InsightLogicProps['variablesOverride']
): StoryEvidenceCharts {
    return {
        canShow: (item) => !!item.query,
        prefetch: () => {},
        // The evidence chart takes the main chart's height, so the explanation panel keeps its size.
        render: ({ query, text }) => (
            <div data-not-quill className="flex h-(--insight-viz-min-height) flex-col">
                <Query
                    key={JSON.stringify(query)}
                    uniqueKey="explain-chart-evidence"
                    query={{
                        ...(query as unknown as InsightVizNode),
                        full: false,
                        showHeader: false,
                        showTable: false,
                    }}
                    context={{ isSeriesHighlighted: (result) => isSeriesNamedIn(seriesNames(result), text) }}
                    filtersOverride={filtersOverride}
                    variablesOverride={variablesOverride}
                    readOnly
                    embedded
                />
            </div>
        ),
        onShow: () => posthog.capture('explain chart evidence chart shown'),
    }
}

export function ExplainChartButton({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { explainAvailable, explainOpen } = useValues(explainChartLogic(insightProps))
    const { openExplain, closeExplain } = useActions(explainChartLogic(insightProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!explainAvailable) {
        return null
    }
    const toggle = (): void => (explainOpen ? closeExplain() : openExplain())
    return todayRailNav ? (
        <span data-quill>
            <Button
                variant="outline"
                size="sm"
                aria-expanded={explainOpen}
                onClick={toggle}
                data-attr="explain-chart-toggle"
            >
                <IconSparkles />
                Explain this chart
            </Button>
        </span>
    ) : (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconSparkles />}
            active={explainOpen}
            onClick={toggle}
            data-attr="explain-chart-toggle"
        >
            Explain this chart
        </LemonButton>
    )
}

export interface InsightExplainChartProps {
    insightProps: InsightLogicProps
    renderChart: (overlay?: ReactNode) => ReactNode
}

/** The chart, with the explanation of what stands out on it beside the chart while the explanation is open. */
export function InsightExplainChart({ insightProps, renderChart }: InsightExplainChartProps): JSX.Element {
    const { explainOpen, explainChartData, formatValue, lookDeeperQuestion } = useValues(
        explainChartLogic(insightProps)
    )
    const { filtersOverride, variablesOverride } = insightProps
    const charts = useMemo(
        () => evidenceCharts(filtersOverride, variablesOverride),
        [filtersOverride, variablesOverride]
    )

    if (!explainOpen || !explainChartData) {
        return <>{renderChart()}</>
    }
    // The explanation is a quill view, so it takes quill's colors. The charts inside it keep PostHog's.
    return (
        <div data-quill>
            <ExplainChartView
                // A new query is a new explanation, so it starts at its summary.
                key={JSON.stringify(explainChartData.query)}
                data={explainChartData}
                renderChart={(overlay) => <div data-not-quill>{renderChart(overlay)}</div>}
                openLink={(url) => window.open(url, '_blank', 'noopener')}
                formatValue={formatValue}
                evidenceCharts={charts}
                action={lookDeeperQuestion ? <ExplainChartLookDeeper question={lookDeeperQuestion} /> : null}
                onPageChange={({ index, fromIndex, source }) =>
                    posthog.capture('explain chart page viewed', {
                        page_index: index,
                        from_page_index: fromIndex,
                        page_count: explainChartData.chapters.length + 1,
                        source,
                    })
                }
            />
        </div>
    )
}
