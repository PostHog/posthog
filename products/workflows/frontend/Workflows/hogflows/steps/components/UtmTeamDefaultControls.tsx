import { useActions, useValues } from 'kea'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { getTeamUtmDefaults, matchesTeamUtmDefaults } from './utmDefaults'
import type { UtmTagValues } from './UtmTagFields'

export interface UtmTeamDefaultControlsProps {
    value: UtmTagValues
    /** Called after the values become the team default, so the email can mark them as following it. */
    onSavedAsTeamDefault: () => void
}

export function UtmTeamDefaultControls({ value, onSavedAsTeamDefault }: UtmTeamDefaultControlsProps): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const defaults = getTeamUtmDefaults(currentTeam?.workflows_config)
    const editDefaultsLink = (
        <Link to={urls.settings('environment-workflows', 'workflows-utm-defaults')} target="_blank">
            Edit team defaults
        </Link>
    )

    if (matchesTeamUtmDefaults(value, defaults)) {
        return <span className="text-xs text-secondary">Using your team's default values. {editDefaultsLink}</span>
    }

    return (
        <div className="flex items-center gap-2 flex-wrap">
            <LemonButton
                type="secondary"
                size="xsmall"
                loading={currentTeamLoading}
                onClick={() => {
                    updateCurrentTeam({
                        workflows_config: {
                            ...currentTeam?.workflows_config,
                            capture_workflows_engagement_events:
                                currentTeam?.workflows_config?.capture_workflows_engagement_events ?? false,
                            email_utm_tags_enabled: true,
                            email_utm_params: value,
                        },
                    })
                    onSavedAsTeamDefault()
                }}
                data-attr="email-utm-save-as-team-default"
            >
                Save as team default
            </LemonButton>
            <span className="text-xs text-secondary">New emails will start with these values. {editDefaultsLink}</span>
        </div>
    )
}
