import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType } from '../rules/types'
import { GroupingRuleModal } from './GroupingRuleModal'
import { groupingRuleModalLogic } from './groupingRuleModalLogic'

export function GroupingRules(): JSX.Element {
    return (
        <RuleList
            ruleType={ErrorTrackingRuleType.Grouping}
            modalLogic={groupingRuleModalLogic}
            modal={<GroupingRuleModal />}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            pageKeyPrefix="grouping-rule"
            description={
                <p>
                    Use the properties of an exception to decide how it should be grouped as an issue. The first rule
                    that matches will be applied.
                </p>
            }
        />
    )
}
