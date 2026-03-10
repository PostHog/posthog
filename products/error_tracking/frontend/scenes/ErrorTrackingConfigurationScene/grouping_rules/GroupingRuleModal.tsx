import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleModal } from '../rules/RuleModal'
import { groupingRuleModalLogic } from './groupingRuleModalLogic'

export function GroupingRuleModal(): JSX.Element {
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
        />
    )
}
