import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import type { AnomalyIntervalEnumApi, AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import type { AnomalyRowRating } from './anomaliesTabLogic'
import { appPath } from './anomalyInsightLinks'
import { AnomalyRowActions } from './AnomalyRowActions'
import { AnomalyRowChart } from './AnomalyRowChart'
import { withAnomalyScoresParam } from './anomalyScoresParam'
import { anomalySeriesLabel } from './anomalySeriesLabel'
import { LastAnomalyLabel } from './LastAnomalyLabel'

const INTERVAL_LABELS: Record<AnomalyIntervalEnumApi, string> = {
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    month: 'Monthly',
}

const MAX_DASHBOARD_LINKS = 2

export interface AnomalyRowProps {
    series: AnomalySeriesApi
    dateFrom: string
    dateTo: string
    rating: AnomalyRowRating | undefined
    onOpenInsight: () => void
    onRate: (rating: AnomalyRowRating) => void
    onCreateAlert: () => void
}

export function AnomalyRow({
    series,
    dateFrom,
    dateTo,
    rating,
    onOpenInsight,
    onRate,
    onCreateAlert,
}: AnomalyRowProps): JSX.Element {
    const shownDashboards = series.dashboards.slice(0, MAX_DASHBOARD_LINKS)
    const moreDashboards = series.dashboards.slice(MAX_DASHBOARD_LINKS)
    return (
        <LemonCard hoverEffect={false} className="p-4 @container" data-attr="anomalies-tab-row">
            <div className="flex flex-col gap-4 @min-[40rem]:flex-row">
                <div className="flex flex-col gap-2 min-w-0 @min-[40rem]:w-72 @min-[40rem]:shrink-0">
                    <div className="min-w-0">
                        <Link
                            to={withAnomalyScoresParam(appPath(series.insight_url))}
                            onClick={onOpenInsight}
                            className="font-semibold block truncate"
                            data-attr="anomalies-tab-open-insight"
                        >
                            {series.insight_name || 'Untitled insight'}
                        </Link>
                        <div className="text-secondary text-sm truncate">
                            {[anomalySeriesLabel(series), INTERVAL_LABELS[series.interval]].filter(Boolean).join(' · ')}
                        </div>
                    </div>
                    {series.last_flagged_bucket && (
                        <LastAnomalyLabel bucketStart={series.last_flagged_bucket} interval={series.interval} />
                    )}
                    {series.dashboards.length > 0 && (
                        <div className="text-secondary text-xs truncate" data-attr="anomalies-tab-row-dashboards">
                            <span>On: </span>
                            {shownDashboards.map((dashboard, index) => (
                                <span key={dashboard.id}>
                                    {index > 0 && ', '}
                                    <Link to={urls.dashboard(dashboard.id)} data-attr="anomalies-tab-open-dashboard">
                                        {dashboard.name || 'Untitled dashboard'}
                                    </Link>
                                </span>
                            ))}
                            {moreDashboards.length > 0 && (
                                <Tooltip
                                    title={moreDashboards
                                        .map((dashboard) => dashboard.name || 'Untitled dashboard')
                                        .join(', ')}
                                >
                                    <span>{` +${moreDashboards.length} more`}</span>
                                </Tooltip>
                            )}
                        </div>
                    )}
                    <AnomalyRowActions series={series} rating={rating} onRate={onRate} onCreateAlert={onCreateAlert} />
                </div>
                <div className="flex-1 min-w-0">
                    <AnomalyRowChart series={series} dateFrom={dateFrom} dateTo={dateTo} />
                </div>
            </div>
        </LemonCard>
    )
}
