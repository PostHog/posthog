import { healthRuleReadings } from './healthCheckValues'
import type { HealthPanelCheck } from './healthPanelChecks'
import { HealthPanelSection } from './HealthPanelSection'
import { HealthReadingList } from './HealthReadingList'

export function HealthCheckRuleSection({
    check,
    units,
    checkedAt,
}: {
    check: HealthPanelCheck
    units: string
    /** When the check ran, for a check that the page reads from a cached answer. */
    checkedAt: string | null
}): JSX.Element | null {
    if (!check.rule) {
        return null
    }
    return (
        <HealthPanelSection title="How it decides">
            <HealthReadingList
                readings={[
                    ...healthRuleReadings(check, check.rule, units),
                    ...(checkedAt ? [{ label: 'Checked', time: checkedAt }] : []),
                ]}
            />
        </HealthPanelSection>
    )
}
