import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { formatReportMetricParts, reportMetricDetailUnit } from '../../utils/reportMetrics'

/** The observation's headline figure: a large mono number with its unit set small beside it. */
export function ReportObservationValue({
    metric,
    value,
}: {
    metric: ReportMetricApi
    value: number | null | undefined
}): JSX.Element {
    const parts = formatReportMetricParts(metric, value)

    if (!parts) {
        return <span className="text-2xl font-semibold leading-tight text-tertiary">Not available</span>
    }
    const unit = reportMetricDetailUnit(metric, parts)

    return (
        <div className="flex flex-wrap items-baseline gap-2.5">
            <span className="font-mono text-2xl font-semibold leading-tight tabular-nums text-primary">
                {parts.value}
            </span>
            {unit ? <span className="font-mono text-xs text-secondary">{unit}</span> : null}
        </div>
    )
}
