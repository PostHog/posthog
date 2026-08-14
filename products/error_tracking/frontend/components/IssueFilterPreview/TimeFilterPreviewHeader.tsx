import { useValues } from 'kea'
import { match } from 'ts-pattern'

import { IconClock, IconTrending } from '@posthog/icons'
import { Tooltip as LemonTooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Skeleton } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { errorTrackingVolumeSparklineLogic } from '../VolumeSparkline/errorTrackingVolumeSparklineLogic'
import type { SparklineDatum, SparklineEvent, VolumeSparklineHoverSelection } from '../VolumeSparkline/types'
import { IssueFilterPreviewHeader } from './IssueFilterPreviewHeader'

interface TimeFilterPreviewHeaderProps {
    sparklineKey: string
}

/** Owns the hover selection so moving across the chart does not re-render the chart subtree. */
export function TimeFilterPreviewHeader({ sparklineKey }: TimeFilterPreviewHeaderProps): JSX.Element {
    const { aggregations, summaryLoading } = useValues(errorTrackingIssueSceneLogic)
    const { hoverSelection } = useValues(errorTrackingVolumeSparklineLogic({ sparklineKey }))

    return (
        <IssueFilterPreviewHeader preview="time" title="Volume" resetIcon={<IconClock />}>
            {match(hoverSelection)
                .when(
                    (data) => shouldRenderIssueMetrics(data),
                    () => <IssueMetrics aggregations={aggregations} summaryLoading={summaryLoading} />
                )
                .with({ kind: 'bin' }, (data) => renderDataPoint(data.datum))
                .with({ kind: 'event' }, (data) => renderEventPoint(data.event))
                .otherwise(() => null)}
        </IssueFilterPreviewHeader>
    )
}

function shouldRenderIssueMetrics(data: VolumeSparklineHoverSelection | null): boolean {
    if (data == null) {
        return true
    }
    if (data.kind === 'bin' && data.datum.value == 0) {
        return true
    }
    return false
}

function IssueMetrics({
    aggregations,
    summaryLoading,
}: {
    aggregations: ErrorTrackingIssueAggregations | undefined
    summaryLoading: boolean
}): JSX.Element {
    const hasSessionCount = aggregations && aggregations.sessions !== 0
    return (
        <div className="flex h-full shrink-0 items-center gap-3">
            {renderMetric('Occurrences', aggregations?.occurrences, summaryLoading)}
            {renderMetric(
                'Sessions',
                aggregations?.sessions,
                summaryLoading,
                hasSessionCount ? undefined : 'No $session_id was set for any event in this issue'
            )}
            {renderMetric('Users', aggregations?.users, summaryLoading)}
        </div>
    )
}

function renderMetric(name: string, value: number | undefined, loading: boolean, tooltip?: string): JSX.Element {
    return (
        <span className="contents">
            {match([loading])
                .with([true], () => (
                    <Skeleton className="h-2 w-[50px]">
                        <span>Loading…</span>
                    </Skeleton>
                ))
                .with([false], () => (
                    <LemonTooltip title={tooltip} delayMs={0} placement="right">
                        <div className="flex items-center gap-1">
                            <div className="inline-block text-lg font-bold">
                                {value == null ? '0' : humanFriendlyLargeNumber(value)}
                            </div>
                            <div className="inline-block text-xs text-muted-foreground">{name}</div>
                        </div>
                    </LemonTooltip>
                ))
                .exhaustive()}
        </span>
    )
}

function renderDataPoint(datum: SparklineDatum): JSX.Element {
    return (
        <div className="flex h-full shrink-0 items-center gap-3">
            {renderMetric('Occurrences', datum.value, false)}
            {datum.isSpike && (
                <div className="flex items-center gap-1.5 text-warning-foreground">
                    <IconTrending className="text-base" />
                    <span className="text-xs font-semibold">Spike</span>
                    <span className="text-xs text-muted-foreground">Click to view details</span>
                </div>
            )}
        </div>
    )
}

function renderEventPoint(event: SparklineEvent<string>): JSX.Element {
    return (
        <div className="flex h-full shrink-0 items-center justify-start">
            <div className="text-sm font-semibold">{dayjs(event.date).utc().format('D MMM YYYY HH:mm [UTC]')}</div>
        </div>
    )
}
