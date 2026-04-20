import { LemonDivider } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import Rules from '../rules/Rules'
import { ErrorTrackingRuleType, ErrorTrackingSuppressionRule } from '../rules/types'

export function ErrorTrackingClientSuppression({ disabled }: { disabled: boolean }): JSX.Element {
    return (
        <Rules<ErrorTrackingSuppressionRule>
            ruleType={ErrorTrackingRuleType.Suppression}
            disabledReason={
                disabled
                    ? 'Suppression rules only apply to autocaptured exceptions. Enable exception autocapture first.'
                    : undefined
            }
        >
            {({ rule, editing }) => {
                return (
                    <>
                        <div className="flex gap-2 justify-between px-2 py-3">
                            <div className="flex gap-1 items-center">
                                <div>Ignore exceptions that match </div>
                                <Rules.Operator rule={rule} editing={editing} />
                                <div>of the following filters:</div>
                            </div>
                            {!disabled && <Rules.Actions rule={rule} editing={editing} />}
                        </div>
                        <LemonDivider className="my-0" />
                        <div className="p-2">
                            <Rules.Filters
                                rule={rule}
                                editing={editing}
                                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                propertyAllowList={{
                                    [TaxonomicFilterGroupType.EventProperties]: [
                                        '$exception_types',
                                        '$exception_values',
                                    ],
                                }}
                            />
                        </div>
                    </>
                )
            }}
        </Rules>
    )
}
