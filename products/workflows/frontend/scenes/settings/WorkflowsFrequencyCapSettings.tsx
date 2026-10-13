import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { teamLogic } from 'scenes/teamLogic'

// Kept in step with the max_value on TeamWorkflowsConfigSerializer.
const MAX_MESSAGES = 1000
const MAX_WINDOW_DAYS = 30

// A cleared number input reports NaN, which must save as null to turn the cap off.
function toInputValue(value: number | null | undefined): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function errorFor(value: number | null, other: number | null, max: number): string | undefined {
    if (value === null) {
        return other === null ? undefined : 'Fill in both fields, or clear both to turn the cap off'
    }
    return Number.isInteger(value) && value >= 1 && value <= max
        ? undefined
        : `Enter a whole number from 1 to ${max.toLocaleString()}`
}

export function WorkflowsFrequencyCapSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedMaxMessages = toInputValue(currentTeam?.workflows_config?.marketing_frequency_cap_max_messages)
    const savedWindowDays = toInputValue(currentTeam?.workflows_config?.marketing_frequency_cap_window_days)

    const [maxMessages, setMaxMessages] = useState<number | null>(savedMaxMessages)
    const [windowDays, setWindowDays] = useState<number | null>(savedWindowDays)

    useEffect(() => {
        setMaxMessages(savedMaxMessages)
        setWindowDays(savedWindowDays)
    }, [savedMaxMessages, savedWindowDays])

    const maxMessagesError = errorFor(maxMessages, windowDays, MAX_MESSAGES)
    const windowDaysError = errorFor(windowDays, maxMessages, MAX_WINDOW_DAYS)
    const unchanged = maxMessages === savedMaxMessages && windowDays === savedWindowDays

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
                        max={MAX_MESSAGES}
                        value={maxMessages ?? undefined}
                        onChange={(value) => setMaxMessages(toInputValue(value))}
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
                        max={MAX_WINDOW_DAYS}
                        value={windowDays ?? undefined}
                        onChange={(value) => setWindowDays(toInputValue(value))}
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
