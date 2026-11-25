import { useValues } from 'kea'

import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { TodayScenePinButton } from '~/layout/today/TodayScenePinButton'

import { scoutDetailActionsLogic } from '../../../logics/scoutDetailActionsLogic'
import { scoutDisplayName } from '../../../utils/scoutRunsWindow'
import { QuillScoutDetailActions } from './QuillScoutDetailActions'
import { ScoutSceneMenuBar } from './ScoutSceneMenuBar'

/**
 * The scout page's scene title under the new navigation: the scout's name, its most used actions and the scene menu
 * bar. The inbox renders it where the list renders its own title, so it takes the standard scene title layout.
 */
export function QuillScoutSceneTitle({ skillName }: { skillName: string }): JSX.Element | null {
    const { config } = useValues(scoutDetailActionsLogic({ skillName }))
    if (!config) {
        return null
    }
    return (
        <>
            <ScoutSceneMenuBar config={config} />
            <SceneTitleSection
                name={scoutDisplayName(config)}
                nameAction={<TodayScenePinButton />}
                description={config.description || null}
                resourceType={{ type: 'inbox' }}
                forceBackTo={{ key: 'scouts', name: 'Scouts', path: urls.inbox('scouts') }}
                actions={<QuillScoutDetailActions config={config} />}
            />
        </>
    )
}
