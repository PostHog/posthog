import { useActions, useValues } from 'kea'

import * as directorPng from '@posthog/brand/hoggies/png/director'
import { Button } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { QuillHighlightPicksStateFrame } from './QuillHighlightPicksStateFrame'

const HedgehogDirector = pngHoggie(directorPng)

export function QuillHighlightPicksReplayOffState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    // Same gate as the settings toggle that writes this field (`ReplayGeneral`).
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <QuillHighlightPicksStateFrame
            size={size}
            image={HedgehogDirector}
            title="Session replay is off"
            body="Scanners watch recordings, so there is nothing for them to see until recording is on. Recordings you already have stay available."
            dataAttr="vision-highlight-picks-replay-off"
            footer={
                <Button
                    variant="link"
                    size="inline"
                    className="mt-1"
                    render={<LinkPrimitive to={urls.settings('environment-replay')} />}
                    data-attr="vision-highlight-picks-replay-off-settings"
                >
                    Replay settings
                </Button>
            }
        >
            <Button
                variant="primary"
                size={size === 'large' ? 'default' : 'sm'}
                className="w-full"
                loading={currentTeamLoading}
                disabledReason={restrictedReason ? 'Ask a project admin to turn on session replay' : undefined}
                onClick={() => updateCurrentTeam({ session_recording_opt_in: true })}
                data-attr="vision-highlight-picks-replay-off-enable"
            >
                Turn on session replay
            </Button>
        </QuillHighlightPicksStateFrame>
    )
}
