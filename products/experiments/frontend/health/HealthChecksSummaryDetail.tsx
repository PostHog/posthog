import { pluralize } from 'lib/utils/strings'

import { type HealthReading, healthSummaryReadings } from './healthCheckValues'
import { type HealthPanelCheck, countHealthChecks, healthChecksVerdict } from './healthPanelChecks'
import { HealthPanelSection } from './HealthPanelSection'
import { HealthReadingList } from './HealthReadingList'

export function HealthChecksSummaryDetail({
    checks,
    issueCount,
    units,
    countedFrom,
    checkedAt,
}: {
    checks: HealthPanelCheck[]
    issueCount: number
    units: string
    /** The start of the exposure count, when the page has an exposure answer. */
    countedFrom: string | null
    /** When the exposure checks ran. */
    checkedAt: string | null
}): JSX.Element {
    const passedCount = countHealthChecks(checks, 'passed')
    const notApplicableCount = countHealthChecks(checks, 'not_applicable')
    const counts = [
        passedCount > 0 ? `${pluralize(passedCount, 'check')} found no issue.` : null,
        notApplicableCount > 0
            ? `${pluralize(notApplicableCount, 'check')} ${notApplicableCount === 1 ? "doesn't" : "don't"} apply to this experiment.`
            : null,
    ]
        .filter(Boolean)
        .join(' ')
    const readings = healthSummaryReadings(checks, units)
    const exposureTimes: HealthReading[] = readings.length
        ? [
              ...(countedFrom ? [{ label: 'Exposures counted from', time: countedFrom, asDate: true }] : []),
              ...(checkedAt ? [{ label: 'Exposure checks ran', time: checkedAt }] : []),
          ]
        : []

    return (
        <div className="flex flex-col gap-4" data-attr="experiment-health-summary-detail">
            <div className="flex flex-col gap-1">
                <h3 className="m-0 text-base font-semibold">{healthChecksVerdict(checks, issueCount)}</h3>
                {counts && <p className="m-0 max-w-prose text-secondary">{counts}</p>}
            </div>
            {readings.length > 0 && (
                <HealthPanelSection title="What the checks read">
                    <HealthReadingList readings={[...readings, ...exposureTimes]} />
                </HealthPanelSection>
            )}
            <p className="m-0 max-w-prose text-secondary">Pick a check to see what it looks for and what it read.</p>
        </div>
    )
}
