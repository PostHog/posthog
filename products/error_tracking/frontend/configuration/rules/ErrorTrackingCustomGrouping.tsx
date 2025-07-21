import { LemonDivider } from '@posthog/lemon-ui'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import ErrorTrackingRules from './ErrorTrackingRules'
import { ErrorTrackingGroupingRule, ErrorTrackingRuleType } from './types'

export function ErrorTrackingCustomGrouping(): JSX.Element {
    return (
        <>
            <p>Use the properties of an exception to decide how it should be grouped as an issue.</p>
            <ErrorTrackingRules<ErrorTrackingGroupingRule> ruleType={ErrorTrackingRuleType.Grouping}>
                {({ rule, editing, disabled }) => {
                    return (
                        <>
                            <div className="flex gap-2 justify-between px-2 py-3">
                                <div className="flex gap-1 items-center">
                                    <div>Group exceptions as a single issue when</div>
                                    <ErrorTrackingRules.Operator rule={rule} editing={editing} />
                                    <div>filters match</div>
                                </div>
                                {!disabled && <ErrorTrackingRules.Actions rule={rule} editing={editing} />}
                            </div>
                            <LemonDivider className="my-0" />
                            <div className="p-2">
                                <ErrorTrackingRules.Filters
                                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                    rule={rule}
                                    editing={editing}
                                />
                            </div>
                        </>
                    )
                }}
            </ErrorTrackingRules>
        </>
    )
}
