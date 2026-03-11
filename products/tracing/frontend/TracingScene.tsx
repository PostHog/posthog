import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

export const scene: SceneExport = {
    component: TracingScene,
    productKey: ProductKey.TRACING,
}

export default function TracingScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Tracing"
                description="Monitor and analyze distributed traces to understand service performance and debug issues."
                resourceType={{
                    type: 'tracing',
                }}
            />
        </SceneContent>
    )
}
