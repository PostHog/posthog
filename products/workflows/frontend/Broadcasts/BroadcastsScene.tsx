import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { BroadcastsTable } from './BroadcastsTable'
import { broadcastsFeaturePreviewGate } from './featurePreviewGate'

export const scene: SceneExport = {
    component: BroadcastsScene,
    productKey: ProductKey.WORKFLOWS,
}

export function BroadcastsScene(): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={broadcastsFeaturePreviewGate}>
            <SceneContent>
                <SceneTitleSection
                    name="Broadcasts"
                    nameSuffix={
                        <LemonTag className="ml-1" type="completion">
                            Beta
                        </LemonTag>
                    }
                    description="Send a one-time or scheduled email to a group of people"
                    resourceType={{ type: 'broadcasts' }}
                    actions={
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton data-attr="new-broadcast" to={urls.broadcastNew()} type="primary" size="small">
                                New broadcast
                            </LemonButton>
                        </AccessControlAction>
                    }
                />
                <BroadcastsTable />
            </SceneContent>
        </FeaturePreviewSceneGate>
    )
}
