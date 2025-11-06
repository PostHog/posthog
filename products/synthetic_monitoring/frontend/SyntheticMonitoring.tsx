import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { MonitorsTable } from './MonitorsTable'
import { syntheticMonitoringLogic } from './syntheticMonitoringLogic'
import { SyntheticMonitoringTab } from './types'

export const scene: SceneExport = {
    component: SyntheticMonitoring,
    logic: syntheticMonitoringLogic,
}

export function SyntheticMonitoring(): JSX.Element {
    const { currentTab } = useValues(syntheticMonitoringLogic)
    const { setTab } = useActions(syntheticMonitoringLogic)

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold">Synthetic Monitoring</h1>
                    <p className="text-muted mt-2">
                        Monitor your endpoints and track uptime, latency, and performance from multiple regions
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    icon={<IconPlusSmall />}
                    onClick={() => router.actions.push(urls.syntheticMonitor('new'))}
                >
                    New monitor
                </LemonButton>
            </div>

            <LemonTabs
                activeKey={currentTab}
                onChange={(key) => setTab(key as SyntheticMonitoringTab)}
                tabs={[
                    {
                        key: SyntheticMonitoringTab.Monitors,
                        label: 'Monitors',
                        content: <MonitorsTable />,
                    },
                    {
                        key: SyntheticMonitoringTab.Settings,
                        label: 'Settings',
                        content: <div className="p-4">Settings coming soon...</div>,
                    },
                ]}
            />
        </div>
    )
}
