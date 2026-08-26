import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { LogMessage } from '~/queries/schema/schema-general'

import { AnomalyBandChart } from 'products/logs/frontend/components/AnomalyBandChart'
import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { LogTag } from 'products/logs/frontend/components/LogTag'
import type { LogsSeriesBandSeriesApi } from 'products/logs/frontend/generated/api.schemas'
import { logsAnomaliesLogic } from 'products/logs/frontend/logsAnomaliesLogic'

export function LogsAnomalies(): JSX.Element {
    const { serviceName } = useValues(logsAnomaliesLogic)
    const { setServiceName } = useActions(logsAnomaliesLogic)

    return (
        <div className="flex flex-col gap-4 flex-1 min-h-0">
            <div className="flex flex-wrap items-center gap-2">
                <span data-attr="logs-anomalies-service">
                    <ServiceFilter
                        value={serviceName ? [serviceName] : []}
                        onChange={(serviceNames) => setServiceName(serviceNames?.[0] ?? null)}
                        // Match the band baseline lookback so a service that recently went
                        // silent still shows up as a suggestion.
                        dateRange={{ date_from: '-42d' }}
                        selectionMode="single"
                        emptyButtonLabel="Choose a service"
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
                Log volume per hour over the last 7 days, against the range seen at the same time of week in the
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
                <SeriesCard key={`${series.namespace}/${series.environment}/${series.severity}`} series={series} />
            ))}
            {hiddenSeriesCount > 0 ? (
                <LemonButton type="secondary" center onClick={showMoreSeries} data-attr="logs-anomalies-show-more">
                    Show more ({hiddenSeriesCount} hidden)
                </LemonButton>
            ) : null}
        </div>
    )
}

// "Show more" grows the visible slice without touching the cards already on screen, so the charts
// they hold should not reconcile again.
const SeriesCard = memo(function SeriesCard({ series }: { series: LogsSeriesBandSeriesApi }): JSX.Element {
    const { openLogsForBucket } = useActions(logsAnomaliesLogic)
    // A banded series carries a band on every bucket, so their absence is the backend's own
    // "still learning" verdict. Restating its week threshold here would let the two drift.
    const learning = series.buckets.length > 0 && series.buckets.every((bucket) => bucket.lower == null)
    return (
        <div className="rounded border bg-surface-primary p-3" data-attr="logs-anomalies-series">
            <div className="mb-2 flex items-center gap-2">
                <LogTag level={series.severity as LogMessage['severity_text']} />
                {series.namespace ? <LemonTag>{series.namespace}</LemonTag> : null}
                {series.environment ? <LemonTag>{series.environment}</LemonTag> : null}
                {learning ? (
                    <LemonTag type="caution" title="This series has too little history for an expected range yet.">
                        Learning baseline
                    </LemonTag>
                ) : null}
            </div>
            <AnomalyBandChart
                buckets={series.buckets}
                onBucketClick={(dateRange) => openLogsForBucket(series.severity, dateRange)}
            />
        </div>
    )
})
