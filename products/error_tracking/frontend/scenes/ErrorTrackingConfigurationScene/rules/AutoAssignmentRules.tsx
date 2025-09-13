import { LemonDivider } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import Rules from './Rules'
import { ErrorTrackingAssignmentRule, ErrorTrackingRuleType } from './types'

export function AutoAssignmentRules(): JSX.Element {
    return (
        <>
            <p>
                Automatically assign newly created issues based on properties of the exception event the first time it
                was seen. The first rule that matches will be applied.
            </p>
            <Rules<ErrorTrackingAssignmentRule> ruleType={ErrorTrackingRuleType.Assignment}>
                {({ rule, editing, disabled }) => {
                    return (
                        <>
                            <div className="flex gap-2 justify-between px-2 py-3">
                                <div className="flex gap-1 items-center">
                                    <div>Assign to</div>
                                    <Rules.Assignee rule={rule} editing={editing} />
                                    <div>when</div>
                                    <Rules.Operator rule={rule} editing={editing} />
                                    <div>filters match</div>
                                </div>
                                {!disabled && (
                                    <Rules.Actions
                                        rule={rule}
                                        editing={editing}
                                        validate={(rule) =>
                                            rule.assignee ? undefined : 'You must choose an assignee for each rule.'
                                        }
                                    />
                                )}
                            </div>
                            <LemonDivider className="my-0" />
                            <div className="p-2">
                                <Rules.Filters
                                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                    rule={rule}
                                    editing={editing}
                                />
                            </div>
                        </>
                    )
                }}
            </Rules>
        </>
    )
}
