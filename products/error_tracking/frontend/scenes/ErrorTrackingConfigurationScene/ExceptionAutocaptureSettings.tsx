import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSwitch } from '@posthog/lemon-ui'
import { LemonDivider } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Link } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/types'

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
                <LemonBanner type="warning" className="mb-4">
                    This configuration only applies to the JS Web SDK. For all other SDKs autocapture can be configured
                    directly in code. See the{' '}
                    <Link to="https://posthog.com/docs/error-tracking/installation">installation instructions</Link> for
                    more details.
                </LemonBanner>
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
                <h3>Suppression rules</h3>
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
