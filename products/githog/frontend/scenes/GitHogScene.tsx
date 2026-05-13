import { LemonButton } from 'lib/lemon-ui/LemonButton'
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
            <div>
                <LemonButton type="primary" to="/githog/pr/1234">
                    Open sample PR #1234
                </LemonButton>
            </div>
        </SceneContent>
    )
}

export default GitHogScene
