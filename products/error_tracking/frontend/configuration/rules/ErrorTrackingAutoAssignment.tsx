import { LemonCard, LemonDivider } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import ErrorTrackingRules from './ErrorTrackingRules'
import { ErrorTrackingAssignmentRule, ErrorTrackingRuleType } from './types'

export function ErrorTrackingAutoAssignment(): JSX.Element {
    return (
        <>
            <p>
                Automatically assign newly created issues based on properties of the exception event the first time it
                was seen.
            </p>
            <ErrorTrackingRules<ErrorTrackingAssignmentRule> ruleType={ErrorTrackingRuleType.Assignment}>
                {({ rule, editable }) => {
                    return (
                        <LemonCard key={rule.id} hoverEffect={false} className="flex flex-col p-0">
                            <div className="flex justify-between gap-2 px-2 py-3">
                                <div className="flex items-center gap-1">
                                    <div>Assign to</div>
                                    <ErrorTrackingRules.Assignee rule={rule} editable={editable} />
                                    <div>when</div>
                                    <ErrorTrackingRules.Operator rule={rule} editable={editable} />
                                    <div>filters match</div>
                                </div>
                                <ErrorTrackingRules.Actions rule={rule} editable={editable} />
                            </div>
                            <LemonDivider className="my-0" />
                            <div className="p-2">
                                <ErrorTrackingRules.Filters
                                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                    rule={rule}
                                    editable={editable}
                                />
                            </div>
                        </LemonCard>
                    )
                }}
            </ErrorTrackingRules>
        </>
    )
}
