import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { useScoutCreateDisabledReason } from '../ScoutCreateModalHost'
import { ScoutTrialsPanel } from './ScoutTrialsPanel'

export function ScoutTrials({ configId }: { configId?: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const editorDisabledReason = useScoutCreateDisabledReason()

    if (currentTeamId !== 2 || !user?.is_staff) {
        return <LemonBanner type="info">Scout trials are available to staff in the internal project.</LemonBanner>
    }
    if (editorDisabledReason) {
        return (
            <LemonBanner type="info">
                Scout trials need editor access to skills. Ask a project admin to change your access level.
            </LemonBanner>
        )
    }

    return <ScoutTrialsPanel teamId={currentTeamId} userId={user.id} configId={configId} />
}
