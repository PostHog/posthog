import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { teamLogic } from 'scenes/teamLogic'

import {
    MAX_FREQUENCY_CAP_MESSAGES,
    MAX_FREQUENCY_CAP_WINDOW_DAYS,
    frequencyCapFieldError,
    toFrequencyCapInputValue,
} from './frequencyCap'
import { unsavedSettingsLogic } from './unsavedSettingsLogic'

export function WorkflowsFrequencyCapSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const unsavedGuard = unsavedSettingsLogic({
        sectionId: 'workflows-frequency-cap',
        message: 'Leave without saving?\nThe frequency cap you entered will be discarded.',
    })
    // useActions alone does not mount a logic, and the guard arms on mount.
    useMountedLogic(unsavedGuard)
    const { setHasUnsavedChanges } = useActions(unsavedGuard)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedMaxMessages = toFrequencyCapInputValue(
        currentTeam?.workflows_config?.marketing_frequency_cap_max_messages
    )
    const savedWindowDays = toFrequencyCapInputValue(currentTeam?.workflows_config?.marketing_frequency_cap_window_days)

    const [maxMessages, setMaxMessages] = useState<number | null>(savedMaxMessages)
    const [windowDays, setWindowDays] = useState<number | null>(savedWindowDays)

    useEffect(() => {
        setMaxMessages(savedMaxMessages)
        setWindowDays(savedWindowDays)
    }, [savedMaxMessages, savedWindowDays])

    const maxMessagesError = frequencyCapFieldError(maxMessages, windowDays, MAX_FREQUENCY_CAP_MESSAGES)
    const windowDaysError = frequencyCapFieldError(windowDays, maxMessages, MAX_FREQUENCY_CAP_WINDOW_DAYS)
    const unchanged = maxMessages === savedMaxMessages && windowDays === savedWindowDays

    useEffect(() => {
        setHasUnsavedChanges(!unchanged)
    }, [unchanged, setHasUnsavedChanges])

    return (
        <div className="@container">
            <div className="flex flex-wrap gap-4">
                <LemonField.Pure
                    className="flex-1 min-w-60"
                    label="Messages per person"
                    htmlFor="workflows-frequency-cap-max-messages"
                    error={maxMessagesError}
                >
                    <LemonInput
                        id="workflows-frequency-cap-max-messages"
                        type="number"
                        min={1}
                        max={MAX_FREQUENCY_CAP_MESSAGES}
                        value={maxMessages ?? undefined}
                        onChange={(value) => setMaxMessages(toFrequencyCapInputValue(value))}
                        placeholder="No cap"
                        disabledReason={restrictedReason}
                        data-attr="workflows-frequency-cap-max-messages"
                    />
                </LemonField.Pure>
                <LemonField.Pure
                    className="flex-1 min-w-60"
                    label="Within this many days"
                    htmlFor="workflows-frequency-cap-window-days"
                    error={windowDaysError}
                >
                    <LemonInput
                        id="workflows-frequency-cap-window-days"
                        type="number"
                        min={1}
                        max={MAX_FREQUENCY_CAP_WINDOW_DAYS}
                        value={windowDays ?? undefined}
                        onChange={(value) => setWindowDays(toFrequencyCapInputValue(value))}
                        placeholder="No cap"
                        disabledReason={restrictedReason}
                        data-attr="workflows-frequency-cap-window-days"
                    />
                </LemonField.Pure>
            </div>
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    loading={currentTeamLoading}
                    onClick={() =>
                        updateCurrentTeam({
                            workflows_config: {
                                capture_workflows_engagement_events:
                                    currentTeam?.workflows_config?.capture_workflows_engagement_events ?? false,
                                marketing_frequency_cap_max_messages: maxMessages,
                                marketing_frequency_cap_window_days: windowDays,
                            },
                        })
                    }
                    disabledReason={
                        restrictedReason ??
                        (maxMessagesError || windowDaysError
                            ? 'Fix the fields above to save'
                            : unchanged
                              ? 'No changes to save'
                              : currentTeamLoading
                                ? 'Saving'
                                : undefined)
                    }
                    data-attr="workflows-frequency-cap-save"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
