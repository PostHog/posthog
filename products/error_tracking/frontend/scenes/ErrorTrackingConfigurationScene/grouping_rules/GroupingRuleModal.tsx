import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ApiRequest } from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleModal } from '../rules/RuleModal'
import { ErrorTrackingGroupingRule, ErrorTrackingRuleType } from '../rules/types'
import { groupingRuleModalLogic } from './groupingRuleModalLogic'

export function GroupingRuleModal(): JSX.Element {
    const { rule } = useValues(groupingRuleModalLogic)
    const groupingRule = rule as ErrorTrackingGroupingRule

    const issueUrl = new ApiRequest()
        .errorTrackingRule(ErrorTrackingRuleType.Grouping, groupingRule.id)
        .addPathComponent('issue')
        .assembleFullUrl(true)

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
                groupingRule.id !== 'new' && groupingRule.issue ? (
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
