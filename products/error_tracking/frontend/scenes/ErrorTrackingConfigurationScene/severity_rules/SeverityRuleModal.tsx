import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { ISSUE_SEVERITY_OPTIONS, IssueSeverityTag } from '../../../components/IssueSeverityTag'
import { RuleModal } from '../rules/RuleModal'
import { severityRuleModalLogic } from './severityRuleModalLogic'

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
                        options={ISSUE_SEVERITY_OPTIONS.map((option) => ({
                            value: option.value,
                            label: <IssueSeverityTag severity={option.value} />,
                        }))}
                    />
                </div>
            }
        />
    )
}
