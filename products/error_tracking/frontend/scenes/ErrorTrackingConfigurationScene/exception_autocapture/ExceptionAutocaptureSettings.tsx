import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { DisableSurvey } from './DisableSurvey'
import { disableSurveyLogic } from './disableSurveyLogic'
import { exceptionAutocaptureLogic } from './exceptionAutocaptureLogic'

export function ExceptionAutocaptureToggle(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { addProductIntent } = useActions(teamLogic)
    const { autocaptureOptIn, settingsLoading } = useValues(exceptionAutocaptureLogic)
    const { setAutocaptureOptIn } = useActions(exceptionAutocaptureLogic)
    const { reportAutocaptureExceptionsToggled } = useActions(eventUsageLogic)
    const { showSurvey, hideSurvey } = useActions(disableSurveyLogic)

    return (
        <>
            <LemonSwitch
                id="posthog-autocapture-exceptions-switch"
                onChange={(checked) => {
                    if (checked) {
                        addProductIntent({
                            product_type: ProductKey.ERROR_TRACKING,
                            intent_context: ProductIntentContext.ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED,
                        })
                    }
                    setAutocaptureOptIn(checked)
                    reportAutocaptureExceptionsToggled(checked)
                    if (checked) {
                        hideSurvey()
                    } else {
                        showSurvey()
                    }
                }}
                checked={autocaptureOptIn}
                disabled={userLoading || settingsLoading}
                label="Enable exception autocapture"
                bordered
            />
            <DisableSurvey />
        </>
    )
}
