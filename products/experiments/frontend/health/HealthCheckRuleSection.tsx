import { healthRuleReadings } from './healthCheckValues'
import type { HealthPanelCheck } from './healthPanelChecks'
import { HealthPanelSection } from './HealthPanelSection'
import { HealthReadingList } from './HealthReadingList'

export function HealthCheckRuleSection({
    check,
    units,
}: {
    check: HealthPanelCheck
    units: string
}): JSX.Element | null {
    if (!check.rule) {
        return null
    }
    return (
        <HealthPanelSection title="How it decides">
            <HealthReadingList readings={healthRuleReadings(check, check.rule, units)} />
        </HealthPanelSection>
    )
}
