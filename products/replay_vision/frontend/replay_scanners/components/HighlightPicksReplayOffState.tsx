import { useActions, useValues } from 'kea'

import * as directorPng from '@posthog/brand/hoggies/png/director'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { HighlightPicksStateFrame } from './HighlightPicksStateFrame'

const HedgehogDirector = pngHoggie(directorPng)

export function HighlightPicksReplayOffState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    // Same gate as the settings toggle that writes this field (`ReplayGeneral`).
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <HighlightPicksStateFrame
            size={size}
            image={HedgehogDirector}
            title="Session replay is off"
            body="Scanners watch recordings, so there is nothing for them to see until recording is on. Recordings you already have stay available."
            dataAttr="vision-highlight-picks-replay-off"
            footer={
                <Link
                    to={urls.settings('environment-replay')}
                    className="mt-1"
                    data-attr="vision-highlight-picks-replay-off-settings"
                >
                    Replay settings
                </Link>
            }
        >
            <LemonButton
                type="primary"
                size={size === 'large' ? 'medium' : 'small'}
                fullWidth
                center
                loading={currentTeamLoading}
                disabledReason={restrictedReason ? 'Ask a project admin to turn on session replay' : null}
                onClick={() => updateCurrentTeam({ session_recording_opt_in: true })}
                data-attr="vision-highlight-picks-replay-off-enable"
            >
                Turn on session replay
            </LemonButton>
        </HighlightPicksStateFrame>
    )
}
