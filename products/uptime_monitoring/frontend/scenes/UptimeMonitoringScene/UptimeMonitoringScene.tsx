import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: UptimeMonitoringScene,
}

// Placeholder row shape until the backend serializer exists and generated types replace it.
type UptimeMonitor = {
    id: string
    name: string
    url: string
}

const COLUMNS: LemonTableColumns<UptimeMonitor> = [
    { title: 'Name', dataIndex: 'name' },
    { title: 'URL', dataIndex: 'url' },
]

export function UptimeMonitoringScene(): JSX.Element {
    const uptimeMonitoringEnabled = useFeatureFlag('UPTIME_MONITORING')

    if (!uptimeMonitoringEnabled) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Uptime monitoring"
                description="Check that your sites and endpoints respond, and find out when they go down."
                resourceType={{ type: 'uptime_monitoring' }}
                actions={
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconPlus />}
                        disabledReason="Creating monitors is not available yet"
                        data-attr="uptime-monitoring-new-monitor"
                    >
                        New monitor
                    </LemonButton>
                }
            />
            <LemonTable
                data-attr="uptime-monitoring-table"
                dataSource={[]}
                columns={COLUMNS}
                rowKey="id"
                emptyState="No monitors yet."
                nouns={['monitor', 'monitors']}
            />
        </SceneContent>
    )
}
