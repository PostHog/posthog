import { useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScoutTrials } from './components/config/scouts/trials/ScoutTrials'

export function ScoutTrialsScene(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)

    if (!user || !currentTeamId) {
        return <Spinner />
    }
    if (currentTeamId !== 2 || !user.is_staff) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent className="ph-no-capture ph-replay-block">
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconArrowLeft />}
                to={urls.inbox('scouts')}
                className="self-start"
                data-attr="scout-comparisons-back"
            >
                Scouts
            </LemonButton>
            <ScoutTrials />
        </SceneContent>
    )
}

export const scene: SceneExport = { component: ScoutTrialsScene }
