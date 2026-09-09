import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

export function HeatmapsEnableCapture(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeamLoading } = useValues(teamLogic)

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (restrictedReason) {
        return (
            <div className="flex flex-col gap-2">
                <LemonButton type="primary" disabledReason={restrictedReason} data-attr="heatmaps-enable-capture">
                    Enable heatmaps
                </LemonButton>
                <p className="text-muted text-xs mb-1">
                    Only project admins can change this. Ask an admin, or turn it on directly in your SDK without admin
                    access:
                </p>
                <CodeSnippet language={Language.JavaScript}>
                    {`posthog.init('<ph_project_api_key>', {\n    api_host: '<ph_client_api_host>',\n    enable_heatmaps: true,\n})`}
                </CodeSnippet>
            </div>
        )
    }

    return (
        <LemonButton
            type="primary"
            onClick={() => updateCurrentTeam({ heatmaps_opt_in: true })}
            loading={currentTeamLoading}
            data-attr="heatmaps-enable-capture"
        >
            Enable heatmaps
        </LemonButton>
    )
}
