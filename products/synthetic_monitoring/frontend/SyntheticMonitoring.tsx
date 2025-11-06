import { useValues } from 'kea'
import { router } from 'kea-router'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessDenied } from 'lib/components/AccessDenied'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { DetectiveHog } from 'lib/components/hedgehogs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { userHasAccess } from '~/lib/utils/accessControlUtils'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MonitorsTable } from './MonitorsTable'
import { syntheticMonitoringLogic } from './syntheticMonitoringLogic'

const SYNTHETIC_MONITORING_PRODUCT_DESCRIPTION =
    'Monitor your endpoints and track uptime, latency, and performance from multiple regions. Get alerted when your services go down or performance degrades.'

export const scene: SceneExport = {
    component: SyntheticMonitoring,
    logic: syntheticMonitoringLogic,
}

export function SyntheticMonitoring(): JSX.Element {
    const { monitors, monitorsLoading } = useValues(syntheticMonitoringLogic)

    if (!userHasAccess(AccessControlResourceType.SyntheticMonitoring, AccessControlLevel.Viewer)) {
        return <AccessDenied object="synthetic monitoring" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.SyntheticMonitoring].name}
                description={sceneConfigurations[Scene.SyntheticMonitoring].description}
                resourceType={{
                    type: sceneConfigurations[Scene.SyntheticMonitoring].iconType || 'default_icon_type',
                }}
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SyntheticMonitoring}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            data-attr="new-monitor"
                            onClick={() => router.actions.push(urls.syntheticMonitor('new'))}
                            type="primary"
                        >
                            New monitor
                        </LemonButton>
                    </AccessControlAction>
                }
            />
            <SceneDivider />
            <ProductIntroduction
                productName="Synthetic monitoring"
                thingName="monitor"
                description={SYNTHETIC_MONITORING_PRODUCT_DESCRIPTION}
                docsURL="https://posthog.com/docs/synthetic-monitoring"
                customHog={DetectiveHog}
                isEmpty={!monitorsLoading && monitors.length === 0}
                action={() => router.actions.push(urls.syntheticMonitor('new'))}
            />

            <MonitorsTable />
        </SceneContent>
    )
}
