import { useAsyncActions, useValues } from 'kea'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { WorkflowsConfig } from '~/types'

import { getTeamUtmDefaults, matchesTeamUtmDefaults } from './utmDefaults'
import type { UtmTagValues } from './UtmTagFields'

export interface UtmTeamDefaultControlsProps {
    value: UtmTagValues
    /** Called after the values become the team default, so the email can mark them as following it. */
    onSavedAsTeamDefault: () => void
}

export function UtmTeamDefaultControls({ value, onSavedAsTeamDefault }: UtmTeamDefaultControlsProps): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useAsyncActions(teamLogic)
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
                disabledReason={currentTeam?.workflows_config ? undefined : 'Loading your workflow settings'}
                onClick={async () => {
                    await updateCurrentTeam({
                        // The API updates only the fields sent. A copy of the cached config would overwrite newer settings.
                        workflows_config: {
                            email_utm_tags_enabled: true,
                            email_utm_params: value,
                        } satisfies Partial<WorkflowsConfig> as WorkflowsConfig,
                    })
                    // A failed save still resolves, so check what was saved. teamLogic shows the error, and the
                    // email keeps its values as its own so a later bulk apply skips them.
                    if (
                        matchesTeamUtmDefaults(
                            value,
                            getTeamUtmDefaults(teamLogic.values.currentTeam?.workflows_config)
                        )
                    ) {
                        onSavedAsTeamDefault()
                    }
                }}
                data-attr="email-utm-save-as-team-default"
            >
                Save as team default
            </LemonButton>
            <span className="text-xs text-secondary">New emails will start with these values. {editDefaultsLink}</span>
        </div>
    )
}
