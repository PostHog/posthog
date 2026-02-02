import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { SupportedPlatforms } from 'lib/components/SupportedPlatforms/SupportedPlatforms'
import { FEATURE_SUPPORT } from 'lib/components/SupportedPlatforms/featureSupport'
import { FEATURE_FLAGS } from 'lib/constants'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { ErrorTrackingIngestionControls } from './IngestionControls'
import { ErrorTrackingClientSuppression } from './SuppressionRules'

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

            <FlaggedFeature flag={FEATURE_FLAGS.ERROR_TRACKING_INGESTION_CONTROLS}>
                <div>
                    <div className="flex justify-between">
                        <h3>Autocapture controls</h3>
                        <SupportedPlatforms config={FEATURE_SUPPORT.errorTrackingSuppressionRules} />
                    </div>
                    <p>
                        Setting autocapture controls allows you to selectively enable exception autocapture based on the
                        user or scenario
                    </p>
                    <ErrorTrackingIngestionControls disabled={!checked} />
                </div>
            </FlaggedFeature>
        </div>
    )
}
