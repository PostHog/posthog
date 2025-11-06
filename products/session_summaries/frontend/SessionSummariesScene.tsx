import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: SessionSummariesScene,
}

export function SessionSummariesScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.SessionSummaries]?.name || 'Session summaries'}
                description={sceneConfigurations[Scene.SessionSummaries]?.description}
                resourceType={{
                    type: sceneConfigurations[Scene.SessionSummaries]?.iconType || 'default_icon_type',
                }}
            />
            <div className="flex items-center justify-center p-8">
                <p className="text-muted">Session summaries content coming soon... Hey?</p>
            </div>
        </SceneContent>
    )
}
