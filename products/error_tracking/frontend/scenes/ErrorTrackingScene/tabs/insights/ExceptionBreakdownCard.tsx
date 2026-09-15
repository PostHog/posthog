import { type ChartTheme } from '@posthog/quill-charts'

import { Text } from 'lib/ui/quill'

import { IntervalType } from '~/types'

import { formatReleaseCount } from 'products/error_tracking/frontend/components/IssueReleases/issueReleases'

import { ExceptionBandChart } from './ExceptionBandChart'
import { ExceptionBandTable } from './ExceptionBandTable'
import { InsightsCard } from './InsightsCard'
import { BandFilter, ExceptionBreakdown } from './releaseBreakdown'

/** One panel of the releases section: exception volume over time, split by one property, plus the
 *  same split as a table. The chart and the table read the same bands, so the colors and the order
 *  they show cannot drift apart. */
export function ExceptionBreakdownCard({
    title,
    breakdown,
    countNoun,
    columnLabel,
    labels,
    loading,
    theme,
    timezone,
    interval,
    incompleteTail,
    onSelectBand,
}: {
    title: string
    breakdown: ExceptionBreakdown
    /** Singular noun for the header count, e.g. "release" reads as "3 releases". */
    countNoun: string
    columnLabel: string
    /** Bucket keys the bands' counts are aligned to. */
    labels: string[]
    loading: boolean
    theme: ChartTheme
    timezone: string
    interval: IntervalType
    incompleteTail: boolean
    onSelectBand: (filters: BandFilter[]) => void
}): JSX.Element {
    return (
        <InsightsCard
            title={title}
            description="Select a value to filter the whole tab down to it"
            action={
                loading ? null : (
                    <Text size="xs" variant="muted">
                        {formatReleaseCount(breakdown.groupCount, countNoun, breakdown.groupCountTruncated)}
                    </Text>
                )
            }
            contentClassName="gap-4"
        >
            <ExceptionBandChart
                bands={breakdown.bands}
                labels={labels}
                loading={loading}
                theme={theme}
                timezone={timezone}
                interval={interval}
                incompleteTail={incompleteTail}
                onSelectBand={onSelectBand}
            />
            <ExceptionBandTable
                bands={breakdown.bands}
                loading={loading}
                columnLabel={columnLabel}
                onSelectBand={onSelectBand}
            />
        </InsightsCard>
    )
}
