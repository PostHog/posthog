import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'
import { LemonDivider } from '@posthog/lemon-ui'

import { SupportedPlatforms } from 'lib/components/SupportedPlatforms/SupportedPlatforms'
import { FEATURE_SUPPORT } from 'lib/components/SupportedPlatforms/featureSupport'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import Rules from './rules/Rules'
import { ErrorTrackingRuleType } from './rules/types'
import { ErrorTrackingSuppressionRule } from './rules/types'

export function ExceptionAutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam, addProductIntent } = useActions(teamLogic)
    const { reportAutocaptureExceptionsToggled } = useActions(eventUsageLogic)

    const checked = !!currentTeam?.autocapture_exceptions_opt_in

    return (
        <div className="flex flex-col gap-y-4">
            <div>
                <div className="flex justify-between">
                    <h3>Exception autocapture</h3>
                    <SupportedPlatforms config={FEATURE_SUPPORT.errorTrackingExceptionAutocapture} />
                </div>
                <p>
                    Captures frontend exceptions thrown on a customers using `onError` and `onUnhandledRejection`
                    listeners in our web JavaScript SDK.
                </p>
                <LemonSwitch
                    id="posthog-autocapture-exceptions-switch"
                    onChange={(checked) => {
                        if (checked) {
                            addProductIntent({
                                product_type: ProductKey.ERROR_TRACKING,
                                intent_context: ProductIntentContext.ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED,
                            })
                        }
                        updateCurrentTeam({
                            autocapture_exceptions_opt_in: checked,
                        })
                        reportAutocaptureExceptionsToggled(checked)
                    }}
                    checked={!!currentTeam?.autocapture_exceptions_opt_in}
                    disabled={userLoading}
                    label="Enable exception autocapture"
                    bordered
                />
            </div>

            <div>
                <div className="flex justify-between">
                    <h3>Suppression rules</h3>
                    <SupportedPlatforms config={FEATURE_SUPPORT.errorTrackingSuppressionRules} />
                </div>
                <p>
                    Autocaptured exceptions can be filtered by type or message to skip capturing certain exceptions in
                    the JS Web SDK
                </p>
                <ErrorTrackingClientSuppression disabled={!checked} />
            </div>
        </div>
    )
}

function ErrorTrackingClientSuppression({ disabled }: { disabled: boolean }): JSX.Element {
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
