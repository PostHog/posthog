import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
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
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                <AccessControlAction
                    resourceType={AccessControlResourceType.Project}
                    minAccessLevel={AccessControlLevel.Admin}
                    userAccessLevel={currentTeam?.user_access_level}
                >
                    <QuillSettingSwitch
                        id="posthog-autocapture-exceptions-switch"
                        label="Enable exception autocapture"
                        checked={!!currentTeam?.autocapture_exceptions_opt_in}
                        onCheckedChange={handleChange}
                        disabled={userLoading}
                    />
                </AccessControlAction>
                <DisableSurvey />
            </div>
        )
    }

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Project}
                minAccessLevel={AccessControlLevel.Admin}
                userAccessLevel={currentTeam?.user_access_level}
            >
                <LemonSwitch
                    id="posthog-autocapture-exceptions-switch"
                    onChange={handleChange}
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
