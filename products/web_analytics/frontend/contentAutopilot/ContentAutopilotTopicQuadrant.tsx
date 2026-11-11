import { useMemo } from 'react'

import { ScatterChart } from '@posthog/quill-charts'
import type { ScatterChartConfig, ScatterSeries } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import type { TopicQuadrantGroup, TopicQuadrantKey, TopicQuadrantPoint } from './topicQuadrant'

const LABELS: Record<TopicQuadrantKey, string> = {
    strong: 'Mentioned and cited',
    mentioned_not_cited: 'Mentioned, not cited',
    cited_not_mentioned: 'Cited, not mentioned',
    weak: 'Neither',
}

const formatRate = (value: number): string => percentage(value, 0)

const CONFIG: ScatterChartConfig<TopicQuadrantPoint> = {
    xAxis: { label: 'Mentioned in answers', domain: [0, 1], tickFormatter: formatRate },
    yAxis: { label: 'Cited as a source', domain: [0, 1], tickFormatter: formatRate },
    showGrid: true,
    legend: { show: true },
    pointRadius: 6,
    tooltip: {
        labelFormatter: (point) => point.meta?.topic ?? point.label,
        xFormatter: (value, point) =>
            `Mentioned ${formatRate(value)} of ${pluralize(point.meta?.answers ?? 0, 'answer')}`,
        yFormatter: (value) => `Cited ${formatRate(value)}`,
    },
}

/** Each topic as a point, mention rate across and cited rate up, grouped by where it sits against the whole set.
 *  Picking a point filters the prompt list to that topic. */
export const ContentAutopilotTopicQuadrant = ({
    groups,
    onSelectTopic,
}: {
    groups: TopicQuadrantGroup[]
    onSelectTopic: (topic: string) => void
}): JSX.Element => {
    const theme = useChartTheme()
    // Read on every render so the colors follow the color mode, and joined so the memo below sees a stable value.
    const colorKey = [
        getColorVar('success'),
        getColorVar('warning'),
        getColorVar('color-accent'),
        getColorVar('danger'),
    ].join('|')
    const series = useMemo<ScatterSeries<TopicQuadrantPoint>[]>(() => {
        const [strong, mentionedNotCited, citedNotMentioned, weak] = colorKey.split('|')
        const colors: Record<TopicQuadrantKey, string> = {
            strong,
            mentioned_not_cited: mentionedNotCited,
            cited_not_mentioned: citedNotMentioned,
            weak,
        }
        return groups
            .filter(({ points }) => points.length)
            .map(({ key, points }) => ({
                key,
                label: LABELS[key],
                color: colors[key],
                points: points.map((point) => ({
                    x: point.mentionRate,
                    y: point.citationRate,
                    label: point.topic,
                    meta: point,
                })),
            }))
    }, [groups, colorKey])
    return (
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader
                title="Topics at a glance"
                description="Each topic against your rates across all prompts. Top right is where you are both named and linked. Pick a topic to see its prompts."
            />
            <div
                className="h-72 min-w-0 flex flex-col p-2"
                data-attr="content-autopilot-prompts-overview-topic-quadrant"
            >
                <ScatterChart<TopicQuadrantPoint>
                    series={series}
                    theme={theme}
                    config={CONFIG}
                    onPointClick={(point) => point.meta && onSelectTopic(point.meta.topic)}
                />
            </div>
        </PagePerformanceCard>
    )
}
