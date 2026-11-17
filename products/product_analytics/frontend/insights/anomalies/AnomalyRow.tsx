import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AnomalyIntervalEnumApi, AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import { AnomalyRowChart } from './AnomalyRowChart'

const INTERVAL_LABELS: Record<AnomalyIntervalEnumApi, string> = {
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    month: 'Monthly',
}

// The API returns an absolute link. Routing its path keeps the click inside the app.
function appPath(url: string): string {
    const parsed = new URL(url, window.location.origin)
    return `${parsed.pathname}${parsed.search}${parsed.hash}`
}

export interface AnomalyRowProps {
    series: AnomalySeriesApi
    dateFrom: string
    dateTo: string
    onOpenInsight: () => void
}

export function AnomalyRow({ series, dateFrom, dateTo, onOpenInsight }: AnomalyRowProps): JSX.Element {
    const coverage = series.coverage
    return (
        <LemonCard hoverEffect={false} className="p-4 @container" data-attr="anomalies-tab-row">
            <div className="flex flex-col gap-4 @min-[40rem]:flex-row">
                <div className="flex flex-col gap-2 min-w-0 @min-[40rem]:w-72 @min-[40rem]:shrink-0">
                    <div className="min-w-0">
                        <Link
                            to={appPath(series.insight_url)}
                            onClick={onOpenInsight}
                            className="font-semibold block truncate"
                            data-attr="anomalies-tab-open-insight"
                        >
                            {series.insight_name || 'Untitled insight'}
                        </Link>
                        <div className="text-secondary text-sm truncate">
                            {[series.series_label || series.breakdown_value, INTERVAL_LABELS[series.interval]]
                                .filter(Boolean)
                                .join(' · ')}
                        </div>
                    </div>
                    <div className="flex flex-wrap gap-1">
                        <LemonTag type="danger">
                            {`Flagged ${series.flagged_buckets} of ${pluralize(series.scored_buckets, series.interval)}`}
                        </LemonTag>
                        <LemonTag type="muted">
                            {series.baseline_rate != null
                                ? `Usually ${percentage(series.baseline_rate, 0)}`
                                : 'No usual rate yet'}
                        </LemonTag>
                    </div>
                    <div className="text-secondary text-xs">
                        <span>
                            {coverage == null || coverage >= 1
                                ? 'All of the range checked'
                                : `${percentage(coverage, 0)} of the range checked`}
                        </span>
                        {series.scored_through && (
                            <>
                                <span>, through </span>
                                <TZLabel time={series.scored_through} />
                            </>
                        )}
                    </div>
                </div>
                <div className="flex-1 min-w-0">
                    <AnomalyRowChart series={series} dateFrom={dateFrom} dateTo={dateTo} />
                </div>
            </div>
        </LemonCard>
    )
}
