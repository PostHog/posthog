import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: FoundersScene,
}

export function FoundersScene(): JSX.Element {
    return (
        <>
            <SceneTitleSection title="Founders" />
            <SceneContent>
                <div className="space-y-4">
                    <p>Welcome to Founder mode.</p>
                </div>
            </SceneContent>
        </>
    )
}
