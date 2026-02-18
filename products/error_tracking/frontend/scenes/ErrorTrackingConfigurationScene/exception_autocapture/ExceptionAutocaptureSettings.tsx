import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { ErrorTrackingIngestionControls } from './IngestionControls'
import { ErrorTrackingClientSuppression } from './SuppressionRules'

export function ExceptionAutocaptureToggle(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam, addProductIntent } = useActions(teamLogic)
    const { reportAutocaptureExceptionsToggled } = useActions(eventUsageLogic)

    return (
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
    )
}

export function ExceptionSuppressionRules(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return <ErrorTrackingClientSuppression disabled={!currentTeam?.autocapture_exceptions_opt_in} />
}

export function ExceptionIngestionControls(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return <ErrorTrackingIngestionControls disabled={!currentTeam?.autocapture_exceptions_opt_in} />
}
