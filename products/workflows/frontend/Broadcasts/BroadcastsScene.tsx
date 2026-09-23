import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { messagingNavTabs } from '../messagingTabs'
import { BroadcastsTable } from './BroadcastsTable'

export const scene: SceneExport = {
    component: BroadcastsScene,
    productKey: ProductKey.WORKFLOWS,
}

export function BroadcastsScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Broadcasts"
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
            <LemonTabs
                activeKey="broadcasts"
                tabs={[{ label: 'Broadcasts', key: 'broadcasts', link: urls.broadcasts() }, ...messagingNavTabs()]}
                sceneInset
            />
            <BroadcastsTable />
        </SceneContent>
    )
}
