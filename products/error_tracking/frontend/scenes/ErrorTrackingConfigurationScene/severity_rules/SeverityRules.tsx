import { Text } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { IssueSeverityTag } from '../../../components/IssueSeverityTag'
import { QuillIssueSeverityTag } from '../../../components/QuillIssueSeverityTag'
import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType, ErrorTrackingSeverityRule } from '../rules/types'
import { SeverityRuleModal } from './SeverityRuleModal'
import { severityRuleModalLogic } from './severityRuleModalLogic'

export function SeverityRules(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const description =
        'Set the initial severity of newly created issues from exception properties. The first matching rule wins. When no rule matches, built-in severity inference is preserved. Existing issues are never changed.'

    return (
        <RuleList
            ruleType={ErrorTrackingRuleType.Severity}
            modalLogic={severityRuleModalLogic}
            modal={<SeverityRuleModal />}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            pageKeyPrefix="severity-rule"
            description={
                todayRailNav ? (
                    <Text size="xs" render={<p className="m-0" />}>
                        {description}
                    </Text>
                ) : (
                    <p>{description}</p>
                )
            }
            renderCardHeaderExtra={(rule: ErrorTrackingSeverityRule) => (
                <>
                    <span className={todayRailNav ? 'text-muted-foreground' : 'text-muted'}>·</span>
                    {todayRailNav ? (
                        <QuillIssueSeverityTag severity={rule.severity} />
                    ) : (
                        <IssueSeverityTag severity={rule.severity} />
                    )}
                </>
            )}
        />
    )
}
