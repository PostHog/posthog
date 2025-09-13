import { LemonDivider } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import Rules from './Rules'
import { GroupingRule, RuleType } from './types'

export function CustomGroupingRules(): JSX.Element {
    return (
        <>
            <p>
                Use the properties of an exception to decide how it should be grouped as an issue. The first rule that
                matches will be applied.
            </p>
            <Rules<GroupingRule> ruleType={RuleType.Grouping}>
                {({ rule, editing, disabled }) => {
                    return (
                        <>
                            <div className="flex gap-2 justify-between px-2 py-3">
                                <div className="flex gap-1 items-center">
                                    <div>Group exceptions as a single issue when</div>
                                    <Rules.Operator rule={rule} editing={editing} />
                                    <div>filters match</div>
                                </div>
                                {!disabled && <Rules.Actions rule={rule} editing={editing} />}
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
