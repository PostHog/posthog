import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { MAX_WAIT_PERIOD_DAYS, surveyGlobalWaitPeriodLogic } from './surveyGlobalWaitPeriodLogic'

export function SurveyGlobalWaitPeriod(): JSX.Element {
    const { enabled, days, saveDisabledReason, editDisabledReason, currentTeamLoading } =
        useValues(surveyGlobalWaitPeriodLogic)
    const { setEnabled, setDays, save } = useActions(surveyGlobalWaitPeriodLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <div className="flex flex-col gap-2 items-start">
            <LemonSwitch
                data-attr="survey-global-wait-period-switch"
                label="Wait between surveys"
                bordered
                checked={enabled}
                onChange={setEnabled}
                disabledReason={restrictedReason ?? editDisabledReason}
            />
            {enabled && (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span>Don't show a user any survey for</span>
                    <LemonInput
                        type="number"
                        size="small"
                        min={1}
                        max={MAX_WAIT_PERIOD_DAYS}
                        value={days}
                        onChange={setDays}
                        className="w-20 tabular-nums"
                        disabledReason={restrictedReason ?? editDisabledReason}
                        data-attr="survey-global-wait-period-input"
                    />
                    <span>days after they see one.</span>
                </div>
            )}
            <LemonButton
                type="primary"
                data-attr="survey-global-wait-period-save"
                loading={currentTeamLoading}
                disabledReason={restrictedReason ?? saveDisabledReason}
                onClick={save}
            >
                Save
            </LemonButton>
        </div>
    )
}
