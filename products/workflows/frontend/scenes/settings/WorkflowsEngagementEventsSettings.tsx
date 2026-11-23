import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { teamLogic } from 'scenes/teamLogic'

export function WorkflowsEngagementEventsSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const enabled = !!currentTeam?.workflows_config?.capture_workflows_engagement_events

    const handleChange = (checked: boolean): void => {
        updateCurrentTeam({
            workflows_config: {
                capture_workflows_engagement_events: checked,
            },
        })
    }

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                id="workflows-capture-engagement-events"
                label="Capture email engagement events"
                checked={enabled}
                onCheckedChange={handleChange}
                disabled={currentTeamLoading}
            />
        )
    }

    return (
        <LemonSwitch
            id="workflows-capture-engagement-events"
            onChange={handleChange}
            checked={enabled}
            disabled={currentTeamLoading}
            label="Capture email engagement events"
            bordered
        />
    )
}
