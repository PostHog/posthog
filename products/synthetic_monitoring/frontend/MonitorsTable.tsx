import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { syntheticMonitoringLogic } from './syntheticMonitoringLogic'
import { SyntheticMonitor } from './types'

export function MonitorsTable(): JSX.Element {
    const { monitors, monitorsLoading } = useValues(syntheticMonitoringLogic)
    const { deleteMonitor, pauseMonitor, resumeMonitor, createAlertWorkflow } = useActions(syntheticMonitoringLogic)

    const columns: LemonTableColumns<SyntheticMonitor> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, monitor) => (
                <div>
                    <div className="font-semibold">{monitor.name}</div>
                    <div className="text-muted text-xs">{monitor.url}</div>
                </div>
            ),
        },
        {
            title: 'Status',
            dataIndex: 'enabled',
            render: (enabled) => (
                <LemonTag type={enabled ? 'success' : 'default'}>{enabled ? 'Enabled' : 'Disabled'}</LemonTag>
            ),
        },
        {
            title: 'Method',
            dataIndex: 'method',
            render: (method) => <span className="font-mono text-xs">{method}</span>,
        },
        {
            title: 'Frequency',
            dataIndex: 'frequency_minutes',
            render: (frequency) => `${frequency} min`,
        },
        {
            title: 'Regions',
            dataIndex: 'regions',
            render: (_, monitor) => {
                const regions = monitor.regions
                return (
                    <div className="flex gap-1 flex-wrap">
                        {regions && regions.length > 0 ? (
                            regions.map((region) => (
                                <LemonTag key={region} type="default">
                                    {region}
                                </LemonTag>
                            ))
                        ) : (
                            <span className="text-muted">No regions</span>
                        )}
                    </div>
                )
            },
        },
        {
            width: 0,
            render: (_, monitor) => (
                <AccessControlAction
                    resourceType={AccessControlResourceType.SyntheticMonitoring}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={monitor.user_access_level}
                >
                    <More
                        overlay={
                            <>
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.SyntheticMonitoring}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={monitor.user_access_level}
                                >
                                    <LemonButton
                                        fullWidth
                                        onClick={() => router.actions.push(urls.syntheticMonitor(monitor.id))}
                                    >
                                        Edit
                                    </LemonButton>
                                </AccessControlAction>
                                <LemonButton fullWidth onClick={() => createAlertWorkflow(monitor.id)}>
                                    Create alert workflow
                                </LemonButton>
                                {monitor.enabled ? (
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.SyntheticMonitoring}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={monitor.user_access_level}
                                    >
                                        <LemonButton fullWidth onClick={() => pauseMonitor(monitor.id)}>
                                            Pause
                                        </LemonButton>
                                    </AccessControlAction>
                                ) : (
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.SyntheticMonitoring}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={monitor.user_access_level}
                                    >
                                        <LemonButton fullWidth onClick={() => resumeMonitor(monitor.id)}>
                                            Resume
                                        </LemonButton>
                                    </AccessControlAction>
                                )}
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.SyntheticMonitoring}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={monitor.user_access_level}
                                >
                                    <LemonButton
                                        fullWidth
                                        status="danger"
                                        onClick={() => {
                                            if (confirm(`Are you sure you want to delete "${monitor.name}"?`)) {
                                                deleteMonitor(monitor.id)
                                            }
                                        }}
                                    >
                                        Delete
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                </AccessControlAction>
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={monitors}
            columns={columns}
            loading={monitorsLoading}
            emptyState={
                <div className="text-center p-8">
                    <h3 className="text-lg font-semibold mb-2">No monitors yet</h3>
                    <p className="text-muted mb-4">
                        Create your first monitor to start tracking uptime and performance
                    </p>
                </div>
            }
            nouns={['monitor', 'monitors']}
        />
    )
}
