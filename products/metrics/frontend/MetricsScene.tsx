import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

export const scene: SceneExport = {
    component: MetricsScene,
    productKey: ProductKey.METRICS,
}

function MetricsScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Metrics"
                description="Monitor and analyze application metrics to understand system performance and health."
                resourceType={{ type: 'metrics' }}
            />
        </SceneContent>
    )
}
