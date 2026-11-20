import { Text } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType } from '../rules/types'
import { GroupingRuleModal } from './GroupingRuleModal'
import { groupingRuleModalLogic } from './groupingRuleModalLogic'

export function GroupingRules(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const description =
        'Use the properties of an exception to decide how it should be grouped as an issue. The first rule that matches will be applied.'

    return (
        <RuleList
            ruleType={ErrorTrackingRuleType.Grouping}
            modalLogic={groupingRuleModalLogic}
            modal={<GroupingRuleModal />}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            pageKeyPrefix="grouping-rule"
            description={
                todayRailNav ? (
                    <Text size="xs" render={<p className="m-0" />}>
                        {description}
                    </Text>
                ) : (
                    <p>{description}</p>
                )
            }
        />
    )
}
