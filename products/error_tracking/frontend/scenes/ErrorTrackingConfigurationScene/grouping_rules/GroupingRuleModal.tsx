import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { RuleModal } from '../rules/RuleModal'
import { ErrorTrackingGroupingRule } from '../rules/types'
import { groupingRuleModalLogic } from './groupingRuleModalLogic'

export function GroupingRuleModal(): JSX.Element {
    const { rule } = useValues(groupingRuleModalLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const groupingRule = rule as ErrorTrackingGroupingRule
    const issueUrl = groupingRule.issue ? urls.errorTrackingIssue(groupingRule.issue.id) : null

    const openIssue = (): void => {
        if (issueUrl) {
            window.open(issueUrl, '_blank')
        }
    }

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
                    todayRailNav ? (
                        <Button variant="outline" onClick={openIssue}>
                            <IconExternal />
                            See issue
                        </Button>
                    ) : (
                        <LemonButton type="secondary" size="small" icon={<IconExternal />} onClick={openIssue}>
                            See issue
                        </LemonButton>
                    )
                ) : undefined
            }
        />
    )
}
