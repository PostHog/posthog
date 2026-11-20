import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'
import { Field, FieldLabel, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { ISSUE_SEVERITY_OPTIONS, IssueSeverity, IssueSeverityTag } from '../../../components/IssueSeverityTag'
import { QuillIssueSeverityTag } from '../../../components/QuillIssueSeverityTag'
import { RuleModal } from '../rules/RuleModal'
import { severityRuleModalLogic } from './severityRuleModalLogic'

export function SeverityRuleModal(): JSX.Element {
    const { rule, hasFilters, hasSeverity } = useValues(severityRuleModalLogic)
    const { updateSeverity } = useActions(severityRuleModalLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
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
                todayRailNav ? (
                    <Field>
                        <FieldLabel htmlFor="severity-rule-severity">Severity</FieldLabel>
                        <Select
                            value={rule.severity ?? null}
                            onValueChange={(value) => value && updateSeverity(value as IssueSeverity)}
                        >
                            <SelectTrigger id="severity-rule-severity" className="w-full">
                                <SelectValue placeholder="Choose severity">
                                    {(severity: IssueSeverity | null) =>
                                        severity ? <QuillIssueSeverityTag severity={severity} /> : 'Choose severity'
                                    }
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {ISSUE_SEVERITY_OPTIONS.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        <QuillIssueSeverityTag severity={option.value} />
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </Field>
                ) : (
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
                )
            }
        />
    )
}
