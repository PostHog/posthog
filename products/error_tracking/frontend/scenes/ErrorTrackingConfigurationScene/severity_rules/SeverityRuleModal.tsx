import { useActions, useValues } from 'kea'

import { LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import {
    ErrorTrackingIssueSeverityRuleEnumApi,
    type ErrorTrackingIssueSeverityRuleEnumApi as Severity,
} from '../../../generated/api.schemas'
import { RuleModal } from '../rules/RuleModal'
import { severityRuleModalLogic } from './severityRuleModalLogic'

const SEVERITY_OPTIONS: { label: string; value: Severity }[] = [
    { label: 'Low', value: ErrorTrackingIssueSeverityRuleEnumApi.Low },
    { label: 'Medium', value: ErrorTrackingIssueSeverityRuleEnumApi.Medium },
    { label: 'High', value: ErrorTrackingIssueSeverityRuleEnumApi.High },
    { label: 'Critical', value: ErrorTrackingIssueSeverityRuleEnumApi.Critical },
]

export const severityTagType = (severity: Severity): 'default' | 'warning' | 'danger' => {
    if (severity === ErrorTrackingIssueSeverityRuleEnumApi.Critical) {
        return 'danger'
    }
    if (severity === ErrorTrackingIssueSeverityRuleEnumApi.High) {
        return 'warning'
    }
    return 'default'
}

export const severityLabel = (severity: Severity): string =>
    SEVERITY_OPTIONS.find((option) => option.value === severity)?.label ?? severity

export function SeverityRuleModal(): JSX.Element {
    const { rule, hasFilters, hasSeverity } = useValues(severityRuleModalLogic)
    const { updateSeverity } = useActions(severityRuleModalLogic)
    const saveDisabledReason = !hasFilters ? 'Add at least one filter' : !hasSeverity ? 'Choose a severity' : undefined

    return (
        <RuleModal
            logic={severityRuleModalLogic}
            ruleLabel="severity"
            description="Matching exceptions set the initial severity when they create a new issue. Existing issues are never changed."
            pageKey="severity-rule-modal"
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            saveDisabledReason={saveDisabledReason}
            suffix={(issuesLink, dateRangeLabel) => (
                <>
                    across {issuesLink} would have matched this severity rule in the last {dateRangeLabel}
                </>
            )}
            extraFields={
                <div>
                    <LemonLabel className="mb-2">Severity</LemonLabel>
                    <LemonSelect
                        fullWidth
                        value={rule.severity ?? undefined}
                        placeholder="Choose severity"
                        onChange={updateSeverity}
                        options={SEVERITY_OPTIONS.map((option) => ({
                            value: option.value,
                            label: <LemonTag type={severityTagType(option.value)}>{option.label}</LemonTag>,
                        }))}
                    />
                </div>
            }
        />
    )
}
