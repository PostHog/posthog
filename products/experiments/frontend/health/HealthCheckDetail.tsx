import { HEALTH_CHECK_STATUS_DISPLAY, healthCheckStatusText } from './healthCheckStatusDisplay'
import { type ListedHealthCheck, healthMeasurementText } from './healthPanelChecks'

export function HealthCheckDetail({ check }: { check: ListedHealthCheck }): JSX.Element {
    return (
        <div className="flex flex-col gap-4" data-attr="experiment-health-check-detail">
            <div className="flex flex-col gap-1">
                <h3 className="m-0 flex items-center gap-2 text-base font-semibold">
                    <span className="flex shrink-0">{HEALTH_CHECK_STATUS_DISPLAY[check.status].icon}</span>
                    <span>{check.name}</span>
                </h3>
                <span className="pl-6 text-xs text-secondary">{healthCheckStatusText(check)}</span>
            </div>
            {check.description && (
                <section className="flex flex-col gap-1">
                    <h4 className="m-0 text-xs font-semibold text-secondary">What it looks for</h4>
                    <p className="m-0 max-w-prose">{check.description}</p>
                </section>
            )}
            {check.measurement && (
                <section className="flex flex-col gap-1">
                    <h4 className="m-0 text-xs font-semibold text-secondary">Result</h4>
                    <p className="m-0 max-w-prose">{healthMeasurementText(check.measurement)}</p>
                </section>
            )}
        </div>
    )
}
