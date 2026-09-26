import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ScoutTrialsPanel } from './ScoutTrialsPanel'

export function ScoutTrials(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)

    if (currentTeamId !== 2 || !user?.is_staff) {
        return <LemonBanner type="info">Scout comparisons are available to staff in the internal project.</LemonBanner>
    }

    return <ScoutTrialsPanel teamId={currentTeamId} userId={user.id} />
}
