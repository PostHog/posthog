import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { urls } from 'scenes/urls'

import { RuleModal } from '../rules/RuleModal'
import { ErrorTrackingGroupingRule } from '../rules/types'
import { groupingRuleModalLogic } from './groupingRuleModalLogic'

export function GroupingRuleModal(): JSX.Element {
    const { rule } = useValues(groupingRuleModalLogic)
    const groupingRule = rule as ErrorTrackingGroupingRule
    const issueUrl = groupingRule.issue ? urls.errorTrackingIssue(groupingRule.issue.id) : null

    return (
        <RuleModal
            logic={groupingRuleModalLogic}
            ruleLabel="grouping"
            description="Matching exceptions will be grouped as a single issue."
            pageKey="grouping-rule-modal"
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            suffix={(issuesLink, dateRangeLabel) => (
                <>
                    across {issuesLink} would have been grouped into one issue in the last {dateRangeLabel}
                </>
            )}
            footerExtra={
                groupingRule.id !== 'new' && issueUrl ? (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconExternal />}
                        onClick={() => window.open(issueUrl, '_blank')}
                    >
                        See issue
                    </LemonButton>
                ) : undefined
            }
        />
    )
}
