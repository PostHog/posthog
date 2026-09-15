import type { ReactNode } from 'react'

import { IconExternal, IconTrends } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { chartOpenTarget } from '../../utils/chartOpenTarget'
import { asReportMetricTrendsQuery, reportMetricFilterCount, reportMetricWindowLabel } from '../../utils/reportMetrics'

/**
 * Frame for the report's key observation: what was observed and how it is counted, then the value
 * and chart the caller has, then the window and filters the numbers come from with a way to open
 * the full insight.
 */
export function ReportObservationCard({
    metric,
    children,
}: {
    metric: ReportMetricApi
    children: ReactNode
}): JSX.Element {
    const query = asReportMetricTrendsQuery(metric.query)
    const openTarget = query ? chartOpenTarget(query) : null
    const filterCount = query ? reportMetricFilterCount(query) : 0
    const windowLabel = query ? reportMetricWindowLabel(query) : null
    const facts = [
        windowLabel,
        filterCount > 0 ? `${filterCount} ${filterCount === 1 ? 'filter' : 'filters'}` : null,
    ].filter((fact): fact is string => fact !== null)

    return (
        <LemonCard
            hoverEffect={false}
            className="@container/report-observation flex flex-col gap-2 p-3"
            data-attr="report-primary-metric"
        >
            <div className="flex flex-col gap-1">
                <h2 className="m-0 text-sm font-semibold leading-snug text-primary">{metric.title}</h2>
                {metric.caption ? <p className="m-0 text-xs leading-snug text-secondary">{metric.caption}</p> : null}
            </div>
            {children}
            {query ? (
                <div
                    className="flex items-center gap-1.5 text-[11px] text-tertiary"
                    data-attr="report-primary-metric-source"
                >
                    <IconTrends className="size-3.5 shrink-0" aria-hidden />
                    <span className="min-w-0 truncate">{facts.length > 0 ? facts.join(' · ') : 'Trends query'}</span>
                    {openTarget ? (
                        <Link
                            to={openTarget.url}
                            target="_blank"
                            disableClientSideRouting
                            className="ml-auto flex shrink-0 items-center gap-0.5 whitespace-nowrap"
                            data-attr="report-primary-metric-open"
                        >
                            {openTarget.label}
                            <IconExternal className="size-3" />
                        </Link>
                    ) : null}
                </div>
            ) : null}
        </LemonCard>
    )
}
