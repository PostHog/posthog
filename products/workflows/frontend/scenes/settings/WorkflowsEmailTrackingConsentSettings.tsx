import { useActions, useValues } from 'kea'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamWorkflowsConfigApi } from '~/generated/core/api.schemas'

type ConsentMode = NonNullable<TeamWorkflowsConfigApi['email_tracking_consent_mode']>

export function WorkflowsEmailTrackingConsentSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const mode: ConsentMode = currentTeam?.workflows_config?.email_tracking_consent_mode ?? 'off'

    return (
        <LemonRadio
            value={mode}
            onChange={(value: ConsentMode) => {
                updateCurrentTeam({
                    workflows_config: {
                        email_tracking_consent_mode: value,
                    },
                })
            }}
            options={[
                {
                    value: 'off',
                    label: 'No consent enforcement',
                    description:
                        'Opens and clicks are tracked according to each email step\'s "Track opens and link clicks" setting.',
                },
                {
                    value: 'opt_out',
                    label: 'Opt-out',
                    description:
                        'Track by default, but not for recipients who have objected to tracking. Marketing emails only; transactional emails are exempt.',
                },
                {
                    value: 'opt_in',
                    label: 'Opt-in',
                    description:
                        'Only track recipients who have explicitly consented. Recipients without a stored consent are sent untracked emails. Marketing emails only; transactional emails are exempt.',
                },
            ]}
            className={currentTeamLoading ? 'opacity-50 pointer-events-none' : undefined}
        />
    )
}
