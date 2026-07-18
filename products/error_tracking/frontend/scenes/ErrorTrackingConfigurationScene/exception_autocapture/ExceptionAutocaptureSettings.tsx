import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DisableSurvey } from './DisableSurvey'
import { disableSurveyLogic } from './disableSurveyLogic'

export function ExceptionAutocaptureToggle(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam, addProductIntent } = useActions(teamLogic)
    const { reportAutocaptureExceptionsToggled } = useActions(eventUsageLogic)
    const { showSurvey, hideSurvey } = useActions(disableSurveyLogic)

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Project}
                minAccessLevel={AccessControlLevel.Admin}
                userAccessLevel={currentTeam?.user_access_level ?? AccessControlLevel.Admin}
            >
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
                        if (checked) {
                            hideSurvey()
                        } else {
                            showSurvey()
                        }
                    }}
                    checked={!!currentTeam?.autocapture_exceptions_opt_in}
                    disabled={userLoading}
                    label="Enable exception autocapture"
                    bordered
                />
            </AccessControlAction>
            <DisableSurvey />
        </>
    )
}
