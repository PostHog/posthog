import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import type { SceneAction, ScenePinned } from '~/layout/scenes/sceneActions/sceneActionModel'

import { RepoSceneMenuBar } from './RepoSceneMenuBar'
import { RepoSwitcher } from './RepoSwitcher'

export interface RepoSceneTitleProps {
    repo: string | null
    description?: string
    /** The flag-off title row. Every action in it must also be in `sceneActions`. */
    actions?: JSX.Element
    /** The page's own actions, merged with the rows every repository page shares. */
    sceneActions?: SceneAction[]
    viewOnGitHubPinned?: ScenePinned
}

export function RepoSceneTitle({
    repo,
    description,
    actions,
    sceneActions,
    viewOnGitHubPinned,
}: RepoSceneTitleProps): JSX.Element {
    return (
        <>
            <RepoSceneMenuBar repo={repo} sceneActions={sceneActions} viewOnGitHubPinned={viewOnGitHubPinned} />
            <SceneTitleSection
                name={repo ?? 'Engineering analytics'}
                nameSuffix={<RepoSwitcher />}
                description={description}
                resourceType={{ type: 'health' }}
                actions={actions}
            />
        </>
    )
}
