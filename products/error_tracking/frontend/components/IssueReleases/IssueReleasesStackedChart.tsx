import { useValues } from 'kea'
import { useMemo } from 'react'

import { DefaultTooltip, TimeSeriesBarChart, createXAxisTickCallback } from '@posthog/quill-charts'
import type { PointClickData, Series, TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { ErrorTrackingReleasesQueryResponse } from '~/queries/schema/schema-general'

import { IssueReleaseStrip, listReleaseStrips } from './issueReleases'

export function IssueReleasesStackedChart({
    releases,
    onSelectStrip,
}: {
    releases: ErrorTrackingReleasesQueryResponse
    onSelectStrip: (strip: IssueReleaseStrip) => void
}): JSX.Element {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)

    const labels = releases.buckets
    const series = useMemo<Series<IssueReleaseStrip>[]>(
        () =>
            listReleaseStrips(releases, theme.colors).map((strip) => ({
                key: strip.key,
                label: strip.fullLabel,
                color: strip.color,
                data: strip.series.counts,
                meta: strip,
            })),
        [releases, theme.colors]
    )
    const tickFormatter = useMemo(() => createXAxisTickCallback({ timezone, allDays: labels }), [labels, timezone])
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            barLayout: 'stacked',
            barCornerRadius: 2,
            bandPadding: 0.15,
            margins: { top: 4 },
            xAxis: { tickFormatter },
            yAxis: { hide: true },
            showAxisLines: { x: true, y: false },
            showTickMarks: false,
            showCrosshair: true,
            showGrid: false,
            tooltip: { placement: 'cursor', pinnable: false, hitArea: 'band' },
        }),
        [tickFormatter]
    )

    const onPointClick = ({ series: clicked }: PointClickData<IssueReleaseStrip>): void => {
        if (clicked.meta) {
            onSelectStrip(clicked.meta)
        }
    }

    return (
        <div className="flex h-56 w-full min-w-0 flex-col">
            <TimeSeriesBarChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                onPointClick={onPointClick}
                dataAttr="error-tracking-issue-releases-stacked"
                tooltip={(context) => (
                    <DefaultTooltip
                        {...context}
                        hideZeroRows
                        sortedByValue
                        showTotal
                        labelFormatter={(label) => dayjs(label).tz(timezone).format('D MMM YYYY HH:mm')}
                        valueFormatter={(value) => `${value} ${value === 1 ? 'occurrence' : 'occurrences'}`}
                    />
                )}
            />
        </div>
    )
}
