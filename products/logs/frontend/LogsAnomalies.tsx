import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import type { LogMessage } from '~/queries/schema/schema-general'

import { AnomalyBandChart, type BucketRange } from 'products/logs/frontend/components/AnomalyBandChart'
import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { LogTag } from 'products/logs/frontend/components/LogTag'
import type { LogsSeriesBandSeriesApi } from 'products/logs/frontend/generated/api.schemas'
import { logsAnomaliesLogic } from 'products/logs/frontend/logsAnomaliesLogic'

const MIN_BASELINE_WEEKS_FOR_BAND = 2

export function LogsAnomalies(): JSX.Element {
    const { serviceName, seriesBands, seriesBandsLoading, visibleSeries, hiddenSeriesCount } =
        useValues(logsAnomaliesLogic)
    const { setServiceName, showMoreSeries } = useActions(logsAnomaliesLogic)

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

            {!serviceName ? (
                <EmptyMessage
                    title="Log volume by series"
                    description="See a week of log volume for each series a service emits, with the expected range learned from previous weeks. Choose a service to start."
                />
            ) : seriesBandsLoading || !seriesBands ? (
                <div className="flex items-center justify-center py-16">
                    <Spinner className="text-2xl" />
                </div>
            ) : seriesBands.series.length === 0 ? (
                <EmptyMessage
                    title="No logs in the last 7 days"
                    description={`${seriesBands.service_name} has no log volume in this window. Choose another service, or check back once it logs again.`}
                />
            ) : (
                <div
                    className="flex flex-col gap-2 flex-1 min-h-0 overflow-y-auto"
                    data-attr="logs-anomalies-band-charts"
                >
                    <div className="text-secondary text-sm">
                        Log volume per hour over the last 7 days, against the range seen at the same time of week in the
                        previous weeks. Marked points fell outside that range. Click a bucket to read its logs.
                    </div>
                    {seriesBands.series_truncated ? (
                        <LemonBanner type="warning" data-attr="logs-anomalies-truncated">
                            This service emits more series than one page can chart. The quietest series were left out.
                        </LemonBanner>
                    ) : null}
                    {visibleSeries.map((series) => (
                        <SeriesCard
                            key={`${series.namespace}/${series.environment}/${series.severity}`}
                            series={series}
                            serviceName={seriesBands.service_name}
                        />
                    ))}
                    {hiddenSeriesCount > 0 ? (
                        <LemonButton
                            type="secondary"
                            center
                            onClick={showMoreSeries}
                            data-attr="logs-anomalies-show-more"
                        >
                            Show more ({hiddenSeriesCount} hidden)
                        </LemonButton>
                    ) : null}
                </div>
            )}
        </div>
    )
}

function SeriesCard({ series, serviceName }: { series: LogsSeriesBandSeriesApi; serviceName: string }): JSX.Element {
    const learning = series.baseline_weeks < MIN_BASELINE_WEEKS_FOR_BAND
    return (
        <div className="rounded border bg-surface-primary p-3" data-attr="logs-anomalies-series">
            <div className="mb-2 flex items-center gap-2">
                <LogTag level={series.severity as LogMessage['severity_text']} />
                {series.namespace ? <LemonTag>{series.namespace}</LemonTag> : null}
                {series.environment ? <LemonTag>{series.environment}</LemonTag> : null}
                {learning ? (
                    <LemonTag
                        type="caution"
                        title="This series has less than 2 full weeks of history, so there is no expected range yet."
                    >
                        Learning baseline
                    </LemonTag>
                ) : null}
            </div>
            <AnomalyBandChart
                buckets={series.buckets}
                onBucketClick={(range) => openLogsForBucket(serviceName, series.severity, range)}
            />
        </div>
    )
}

function openLogsForBucket(serviceName: string, severity: string, range: BucketRange): void {
    router.actions.push(
        combineUrl(urls.logs(), {
            activeTab: 'viewer',
            serviceNames: serviceName,
            severityLevels: severity,
            dateRange: { date_from: range.dateFrom, date_to: range.dateTo },
        }).url
    )
}
