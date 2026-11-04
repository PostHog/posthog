import { TZLabel } from 'lib/components/TZLabel'

import type { SignalReportCheckApi, SignalReportStatusEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringPeriodLabel } from './reportCheckPresentation'

function observationWindowEndLabel(state: string): string {
    return state === 'monitoring'
        ? 'Final verification scheduled for: '
        : ['window_ended', 'verifying', 'assessment_required', 'verification_complete'].includes(state)
          ? 'Window ended: '
          : 'Window end: '
}

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
    const state = timing?.final_verification_state ?? timing?.state ?? ''
    return (
        <span className="flex min-w-0 flex-col gap-1">
            <span>{detail}</span>
            {timing && check.soak_minutes != null && (
                <span>{`Observation window: ${monitoringPeriodLabel(check.soak_minutes)}.`}</span>
            )}
            {timing?.next_measurement_at && (
                <span>
                    <span>{state === 'due' ? 'Measurement due since: ' : 'Next measurement: '}</span>
                    <TZLabel time={timing.next_measurement_at} timestampStyle="absolute" formatDate="MMM D" />
                </span>
            )}
            {timing?.ends_at && (
                <span>
                    <span>{observationWindowEndLabel(state)}</span>
                    <TZLabel time={timing.ends_at} timestampStyle="absolute" formatDate="MMM D" />
                </span>
            )}
        </span>
    )
}
