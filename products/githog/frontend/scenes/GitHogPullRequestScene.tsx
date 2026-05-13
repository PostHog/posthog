import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export interface GitHogPullRequestSceneProps {
    owner: string
    name: string
    number: string
}

export const scene: SceneExport<GitHogPullRequestSceneProps> = {
    component: GitHogPullRequestScene,
    paramsToProps: ({ params: { owner, name, number } }) => ({
        owner: decodeURIComponent(owner ?? ''),
        name: decodeURIComponent(name ?? ''),
        number: number ?? '',
    }),
}

export function GitHogPullRequestScene({ owner, name, number }: GitHogPullRequestSceneProps): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name={`${owner}/${name} #${number}`}
                description="Pull request details."
                resourceType={{ type: 'githog' }}
            />
        </SceneContent>
    )
}

export default GitHogPullRequestScene
