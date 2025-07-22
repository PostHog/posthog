import { LemonSwitch } from '@posthog/lemon-ui'
import { LemonDivider } from '@posthog/lemon-ui'
import { useValues, useActions } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Link } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/types'

import ErrorTrackingRules from './rules/ErrorTrackingRules'
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
                <p>
                    Captures frontend exceptions thrown on a customers using `onError` and `onUnhandledRejection`
                    listeners in our web JavaScript SDK.
                </p>
                <p>
                    Autocapture is also available for our{' '}
                    <Link
                        to="https://posthog.com/docs/error-tracking/installation?tab=Python#setting-up-python-exception-autocapture"
                        target="_blank"
                    >
                        Python SDK
                    </Link>
                    , where it can be configured directly in code.
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
                <p>You can filter by type or message content to skip capturing certain exceptions on the client</p>
                <ErrorTrackingClientSuppression disabled={!checked} />
            </div>
        </div>
    )
}

function ErrorTrackingClientSuppression({ disabled }: { disabled: boolean }): JSX.Element {
    return (
        <ErrorTrackingRules<ErrorTrackingSuppressionRule>
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
                                <ErrorTrackingRules.Operator rule={rule} editing={editing} />
                                <div>of the following filters:</div>
                            </div>
                            {!disabled && <ErrorTrackingRules.Actions rule={rule} editing={editing} />}
                        </div>
                        <LemonDivider className="my-0" />
                        <div className="p-2">
                            <ErrorTrackingRules.Filters
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
        </ErrorTrackingRules>
    )
}
