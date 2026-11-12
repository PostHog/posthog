import { type ReactElement, useMemo, useState } from 'react'
import { Text, View } from 'react-native'

import { formatClock } from '@/lib/dates'
import { groupThousands, plural } from '@/model/adapters/text'
import type { LiveActivity, LiveMinute } from '@/model/live'
import { ChartLegend, useChartLegend } from '@/ui/chart/ChartLegend'
import { MetricChart } from '@/ui/chart/MetricChart'
import { seriesColor } from '@/ui/chart/palette'
import type { ChartPoint, ChartSeries } from '@/ui/chart/types'
import { createStyles, useTheme } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { LiveCard, LiveCardNote, NOT_LOADED_TEXT } from './LiveCard'

const SELECTION_ID = 'live-activity'
const CHART_HEIGHT = 168

function caption(minute: LiveMinute): string {
    return `${formatClock(new Date(minute.at))} · ${plural(minute.users, 'visitor')} · ${plural(minute.pageviews, 'pageview')}`
}

/**
 * Active users per minute as the web draws them: new visitors stacked under returning visitors, one bar per minute.
 * The line under the chart names the scrubbed minute, or the current one, with its pageviews, which the bars leave out.
 */
export function LiveActivityCard({ activity }: { activity: LiveActivity | null }): ReactElement {
    const { colors, chartPalette } = useTheme()
    const styles = useStyles()
    const legend = useChartLegend()
    const minutes = activity?.minutes
    // A selection belongs to one read's minutes, so the caption falls back to the current minute after each read.
    const [selection, setSelection] = useState<{ minutes: LiveMinute[]; at: number } | null>(null)
    const selectedAt = selection && selection.minutes === minutes ? selection.at : null
    const series = useMemo<ChartSeries[]>(() => {
        if (!minutes) {
            return []
        }
        const last = minutes.length - 1
        const points = (value: (minute: LiveMinute) => number): ChartPoint[] =>
            minutes.map((minute) => ({ at: minute.at, value: value(minute) }))
        return [
            {
                key: 'new',
                label: 'New visitors',
                color: colors.diffGreen,
                points: points((minute) => minute.newUsers),
                incompleteFrom: last,
            },
            {
                key: 'returning',
                label: 'Returning visitors',
                color: seriesColor(0, chartPalette),
                points: points((minute) => minute.returningUsers),
                incompleteFrom: last,
            },
        ]
    }, [minutes, colors.diffGreen, chartPalette])

    let body: ReactElement
    if (!minutes) {
        body = <LiveCardNote text={NOT_LOADED_TEXT} testID="live-activity-not-loaded" />
    } else if (minutes.every((minute) => minute.users === 0)) {
        body = <LiveCardNote text="No activity in the last 30 minutes" testID="live-activity-empty" />
    } else {
        const shown = minutes.find((minute) => minute.at === selectedAt) ?? minutes[minutes.length - 1]
        body = (
            <View style={styles.body}>
                <MetricChart
                    series={series}
                    kind="bar"
                    barLayout="stacked"
                    fitAllBars
                    interval="minute"
                    label="Active users per minute"
                    formatValue={(value) => groupThousands(value)}
                    variant="inline"
                    height={CHART_HEIGHT}
                    hiddenKeys={legend.state.hiddenKeys}
                    onSelect={(point) => {
                        if (point) {
                            setSelection({ minutes, at: point.at })
                        }
                    }}
                    selectionId={SELECTION_ID}
                    trackingContext="view"
                    accessibilitySummary="Active users per minute, stacked bar chart, last 30 minutes"
                    testID="live-activity-chart"
                />
                {shown ? (
                    <Text style={styles.caption} testID="live-activity-caption">
                        {caption(shown)}
                    </Text>
                ) : null}
                <ChartLegend
                    series={series}
                    state={legend.state}
                    onChange={legend.setState}
                    selectionId={SELECTION_ID}
                    testID="live-activity-legend"
                />
            </View>
        )
    }
    return (
        <LiveCard title="Active users per minute" meta="Last 30 minutes" testID="live-activity">
            {body}
        </LiveCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: {
        gap: 10,
    },
    caption: {
        ...type.meta,
        color: colors.secondary,
        fontVariant: ['tabular-nums'],
    },
}))
