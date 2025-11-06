import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { DetectiveHog } from 'lib/components/hedgehogs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { MonitorsTable } from './MonitorsTable'
import { syntheticMonitoringLogic } from './syntheticMonitoringLogic'
import { SyntheticMonitoringTab } from './types'

const SYNTHETIC_MONITORING_PRODUCT_DESCRIPTION =
    'Monitor your endpoints and track uptime, latency, and performance from multiple regions. Get alerted when your services go down or performance degrades.'

export const scene: SceneExport = {
    component: SyntheticMonitoring,
    logic: syntheticMonitoringLogic,
}

export function SyntheticMonitoring(): JSX.Element {
    const { tab, monitors, monitorsLoading } = useValues(syntheticMonitoringLogic)
    const { setTab } = useActions(syntheticMonitoringLogic)

    const tabs: LemonTab<SyntheticMonitoringTab>[] = [
        {
            key: SyntheticMonitoringTab.Monitors,
            label: 'Monitors',
            content: <MonitorsTable />,
            link: urls.syntheticMonitoring(),
        },
        {
            key: SyntheticMonitoringTab.Settings,
            label: 'Settings',
            content: <div className="p-4">Settings coming soon...</div>,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.SyntheticMonitoring].name}
                description={sceneConfigurations[Scene.SyntheticMonitoring].description}
                resourceType={{
                    type: sceneConfigurations[Scene.SyntheticMonitoring].iconType || 'default_icon_type',
                }}
                actions={
                    <LemonButton
                        size="small"
                        data-attr="new-monitor"
                        onClick={() => router.actions.push(urls.syntheticMonitor('new'))}
                        type="primary"
                    >
                        New monitor
                    </LemonButton>
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
            <LemonTabs
                activeKey={tab}
                onChange={(key) => setTab(key as SyntheticMonitoringTab)}
                data-attr="synthetic-monitoring-tabs"
                tabs={tabs}
                sceneInset
            />
        </SceneContent>
    )
}
