import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ClustersView } from './ClustersView'
import { clustersLogic } from './clustersLogic'

export const scene: SceneExport = {
    component: LLMAnalyticsClustersScene,
    logic: clustersLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

export function LLMAnalyticsClustersScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Clusters"
                description="Discover patterns and clusters in your LLM usage."
                resourceType={{ type: 'llm_clusters' }}
            />
            <ClustersView />
        </SceneContent>
    )
}
