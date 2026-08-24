import { LemonTag } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType, ErrorTrackingSeverityRule } from '../rules/types'
import { SeverityRuleModal, severityLabel, severityTagType } from './SeverityRuleModal'
import { severityRuleModalLogic } from './severityRuleModalLogic'

export function SeverityRules(): JSX.Element {
    return (
        <RuleList
            ruleType={ErrorTrackingRuleType.Severity}
            modalLogic={severityRuleModalLogic}
            modal={<SeverityRuleModal />}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            pageKeyPrefix="severity-rule"
            description={
                <p>
                    Set the initial severity of newly created issues from exception properties. The first matching rule
                    wins. When no rule matches, built-in severity inference is preserved. Existing issues are never
                    changed.
                </p>
            }
            renderCardHeaderExtra={(rule: ErrorTrackingSeverityRule) => (
                <>
                    <span className="text-muted">·</span>
                    <LemonTag type={severityTagType(rule.severity)}>{severityLabel(rule.severity)}</LemonTag>
                </>
            )}
        />
    )
}
