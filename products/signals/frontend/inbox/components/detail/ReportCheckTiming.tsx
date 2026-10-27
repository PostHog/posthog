import { TZLabel } from 'lib/components/TZLabel'

import type { SignalReportCheckApi, SignalReportStatusEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringPeriodLabel } from './reportCheckPresentation'

export function ReportCheckTiming({
    check,
    reportStatus,
    detail,
}: {
    check: SignalReportCheckApi
    reportStatus: SignalReportStatusEnumApi
    detail: string
}): JSX.Element {
    const timing = reportStatus === 'monitoring' ? check.monitoring_timing : null
    return (
        <span className="flex min-w-0 flex-col gap-1">
            <span>{detail}</span>
            {timing && check.soak_minutes != null && (
                <span>{`Observation window: ${monitoringPeriodLabel(check.soak_minutes)}.`}</span>
            )}
            {timing?.next_measurement_at && (
                <span>
                    <span>{timing.state === 'due' ? 'Measurement due since: ' : 'Next measurement: '}</span>
                    <TZLabel time={timing.next_measurement_at} timestampStyle="absolute" formatDate="MMM D" />
                </span>
            )}
            {timing?.ends_at && (
                <span>
                    <span>{timing.state === 'window_ended' ? 'Window ended: ' : 'Window end: '}</span>
                    <TZLabel time={timing.ends_at} timestampStyle="absolute" formatDate="MMM D" />
                </span>
            )}
        </span>
    )
}
