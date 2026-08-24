import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { TracingAlertingSection } from './TracingAlertingSection'

export const scene: SceneExport = {
    component: TracingAlertsScene,
    productKey: ProductKey.TRACING,
}

export function TracingAlertsScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Alerts"
                description="Get notified when traces cross a threshold you define."
                resourceType={{ type: 'tracing' }}
                forceBackTo={{ key: 'tracing', name: 'Tracing', path: urls.tracing() }}
            />
            <TracingAlertingSection />
        </SceneContent>
    )
}

export default TracingAlertsScene
