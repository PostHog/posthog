import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { DateRangePicker } from 'lib/components/DateFilter/DateRangePicker/DateRangePicker'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { LogMessage } from '~/queries/schema/schema-general'
import type { DateMappingOption } from '~/types'

import { AnomalyBandChart } from 'products/logs/frontend/components/AnomalyBandChart'
import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { LogTag } from 'products/logs/frontend/components/LogTag'
import type { LogsSeriesBandSeriesApi } from 'products/logs/frontend/generated/api.schemas'
import { logsAnomaliesLogic } from 'products/logs/frontend/logsAnomaliesLogic'

// The backend charts at most a week at a time and cannot reach past 35 days, because the
// source table drops what it would need. Rolling options only: a fixed span needs no calendar,
// so there is no week boundary to snap and no timezone to snap it in. Pick an arbitrary week
// through the picker's own start and end fields.
const DATE_OPTIONS: DateMappingOption[] = [
    { key: 'Last 24 hours', values: ['-24h'], defaultInterval: 'hour' },
    { key: 'Last 3 days', values: ['-3d'], defaultInterval: 'hour' },
    { key: 'Last 7 days', values: ['-7d'], defaultInterval: 'hour' },
]

export function LogsAnomalies(): JSX.Element {
    const { serviceName, dateRange } = useValues(logsAnomaliesLogic)
    const { setServiceName, setDateRange } = useActions(logsAnomaliesLogic)

    return (
        <div className="flex flex-col gap-4 flex-1 min-h-0">
            <div className="flex flex-wrap items-center gap-2">
                <span data-attr="logs-anomalies-service">
                    <ServiceFilter
                        value={serviceName ? [serviceName] : []}
                        onChange={(serviceNames) => setServiceName(serviceNames?.[0] ?? null)}
                        // Suggestions span the whole retention rather than the charted window: a
                        // service that went silent is the one worth charting, and following the
                        // window would drop it from the list exactly when it matters.
                        dateRange={{ date_from: '-42d' }}
                        selectionMode="single"
                        emptyButtonLabel="Choose a service"
                    />
                </span>
                <span data-attr="logs-anomalies-date-range">
                    <DateRangePicker
                        dateRange={dateRange}
                        setDateRange={setDateRange}
                        logicKey="logs-anomalies"
                        dateOptions={DATE_OPTIONS}
                        allowedRollingDateOptions={['hours', 'days']}
                    />
                </span>
            </div>
            <SeriesBands />
        </div>
    )
}

function SeriesBands(): JSX.Element {
    const { serviceName, seriesBands, seriesBandsError, seriesBandsLoading, visibleSeries, hiddenSeriesCount } =
        useValues(logsAnomaliesLogic)
    const { loadSeriesBands, showMoreSeries } = useActions(logsAnomaliesLogic)

    if (!serviceName) {
        return (
            <EmptyMessage
                title="Log volume by series"
                description="See a week of log volume for each series a service emits, with the expected range learned from previous weeks. Choose a service to start."
            />
        )
    }

    if (seriesBandsError) {
        // LemonBanner takes a fixed prop set, so a data-attr on it would never reach the DOM.
        return (
            <div data-attr="logs-anomalies-error">
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadSeriesBands }}>
                    Couldn't load the charts for {serviceName}. {seriesBandsError}
                </LemonBanner>
            </div>
        )
    }

    if (seriesBandsLoading || !seriesBands) {
        return (
            <div className="flex items-center justify-center py-16">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    if (seriesBands.series.length === 0) {
        // A service that logged earlier in the baseline window still returns zero-filled series,
        // so an empty list means nothing was logged across the baseline either.
        return (
            <EmptyMessage
                title="No logs to chart"
                description={`${seriesBands.service_name} has no recent log volume. Choose another service, or check back once it logs again.`}
            />
        )
    }

    return (
        <div className="flex flex-col gap-2 flex-1 min-h-0 overflow-y-auto" data-attr="logs-anomalies-band-charts">
            <div className="text-secondary text-sm">
                Log volume per hour from {formatWindowBound(seriesBands.window_start)} to{' '}
                {formatWindowBound(seriesBands.window_end)}, against the range seen at the same time of week in the
                previous weeks. Marked points fell outside that range. Click a bucket to read its logs.
            </div>
            {seriesBands.series_truncated ? (
                <div data-attr="logs-anomalies-truncated">
                    <LemonBanner type="warning">
                        This service emits more series than one page can chart. The quietest series were left out.
                    </LemonBanner>
                </div>
            ) : null}
            {visibleSeries.map((series) => (
                <SeriesCard
                    key={`${series.namespace}/${series.environment}/${series.severity}`}
                    series={series}
                    windowEnd={seriesBands.window_end}
                />
            ))}
            {hiddenSeriesCount > 0 ? (
                <LemonButton type="secondary" center onClick={showMoreSeries} data-attr="logs-anomalies-show-more">
                    Show more ({hiddenSeriesCount} hidden)
                </LemonButton>
            ) : null}
        </div>
    )
}

export function learningBaselineLabel(bandReadyAt: string, windowEnd: string): string {
    // Round up: a wait of just over two days still needs a third day of data.
    const days = Math.max(1, Math.ceil(dayjs(bandReadyAt).diff(windowEnd, 'day', true)))
    return `Learning baseline · ${days} more ${days === 1 ? 'day' : 'days'}`
}

function formatWindowBound(timestamp: string): string {
    return dayjs(timestamp).format('MMM D, HH:mm')
}

function formatDay(timestamp: string): string {
    return dayjs(timestamp).format('MMM D, YYYY')
}

// "Show more" grows the visible slice without touching the cards already on screen, so the charts
// they hold should not reconcile again.
const SeriesCard = memo(function SeriesCard({
    series,
    windowEnd,
}: {
    series: LogsSeriesBandSeriesApi
    windowEnd: string
}): JSX.Element {
    const { openLogsForBucket } = useActions(logsAnomaliesLogic)
    // The backend dates the wait, so its history threshold stays out of here and the two cannot drift.
    const bandReadyAt = series.band_ready_at
    return (
        <div className="rounded border bg-surface-primary p-3" data-attr="logs-anomalies-series">
            <div className="mb-2 flex items-center gap-2">
                <LogTag level={series.severity as LogMessage['severity_text']} />
                {series.namespace ? <LemonTag>{series.namespace}</LemonTag> : null}
                {series.environment ? <LemonTag>{series.environment}</LemonTag> : null}
                {bandReadyAt ? (
                    <Tooltip
                        title={`First seen ${formatDay(series.history_start)}. The expected range starts ${formatDay(
                            bandReadyAt
                        )}.`}
                    >
                        <LemonTag type="caution">{learningBaselineLabel(bandReadyAt, windowEnd)}</LemonTag>
                    </Tooltip>
                ) : null}
            </div>
            <AnomalyBandChart
                buckets={series.buckets}
                onBucketClick={(dateRange) => openLogsForBucket(series.severity, dateRange)}
            />
        </div>
    )
})
