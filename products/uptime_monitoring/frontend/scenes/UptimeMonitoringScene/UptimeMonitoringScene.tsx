import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { UptimeMonitorApi } from '../../generated/api.schemas'
import { CreateUptimeMonitorModal } from './CreateUptimeMonitorModal'
import { formatInterval, uptimeMonitoringSceneLogic } from './uptimeMonitoringSceneLogic'

export const scene: SceneExport = {
    component: UptimeMonitoringScene,
    logic: uptimeMonitoringSceneLogic,
}

export function UptimeMonitoringScene(): JSX.Element {
    const uptimeMonitoringEnabled = useFeatureFlag('UPTIME_MONITORING')
    const { monitors, monitorsLoading } = useValues(uptimeMonitoringSceneLogic)
    const { openCreateModal, confirmDeleteMonitor } = useActions(uptimeMonitoringSceneLogic)

    if (!uptimeMonitoringEnabled) {
        return <NotFound object="page" />
    }

    const columns: LemonTableColumns<UptimeMonitorApi> = [
        { title: 'Name', dataIndex: 'name' },
        {
            title: 'URL',
            dataIndex: 'url',
            render: (_, monitor) => <LemonTableLink to={monitor.url} target="_blank" title={monitor.url} />,
        },
        {
            title: 'Interval',
            dataIndex: 'interval_seconds',
            render: (_, monitor) => formatInterval(monitor.interval_seconds),
        },
        {
            title: 'State',
            dataIndex: 'enabled',
            render: (_, monitor) =>
                monitor.enabled ? <LemonTag type="success">Enabled</LemonTag> : <LemonTag>Paused</LemonTag>,
        },
        {
            width: 0,
            render: (_, monitor) => (
                <More
                    overlay={
                        <LemonButton
                            status="danger"
                            fullWidth
                            onClick={() => confirmDeleteMonitor(monitor)}
                            disabledReason={monitorsLoading ? 'Loading monitors' : undefined}
                            data-attr="uptime-monitoring-delete-monitor"
                        >
                            Delete
                        </LemonButton>
                    }
                />
            ),
        },
    ]

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
                        onClick={openCreateModal}
                        data-attr="uptime-monitoring-new-monitor"
                    >
                        New monitor
                    </LemonButton>
                }
            />
            <LemonBanner type="info">
                Uptime monitoring is in alpha. Monitors don't run checks yet, so you won't get alerts.
            </LemonBanner>
            <LemonTable
                data-attr="uptime-monitoring-table"
                dataSource={monitors ?? []}
                loading={monitorsLoading}
                columns={columns}
                rowKey="id"
                emptyState={
                    monitors === null
                        ? "Couldn't load monitors. Refresh the page to try again."
                        : 'No monitors yet. Create one to choose the URLs PostHog should check.'
                }
                nouns={['monitor', 'monitors']}
            />
            <CreateUptimeMonitorModal />
        </SceneContent>
    )
}
