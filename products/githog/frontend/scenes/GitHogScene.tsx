import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: GitHogScene,
}

export function GitHogScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection name="GitHog" resourceType={{ type: 'githog' }} />
            <p className="text-muted">GitHog is coming soon.</p>
        </SceneContent>
    )
}

export default GitHogScene
