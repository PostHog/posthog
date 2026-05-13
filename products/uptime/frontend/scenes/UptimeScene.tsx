import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { Monitor, Ping, uptimeSceneLogic } from './uptimeSceneLogic'

export const scene: SceneExport = {
    component: UptimeScene,
    logic: uptimeSceneLogic,
}

export function UptimeScene(): JSX.Element {
    const { monitors, monitorsLoading, selectedMonitorId, pings, pingsLoading } = useValues(uptimeSceneLogic)
    const { selectMonitor, pingNow } = useActions(uptimeSceneLogic)

    const selectedMonitor = monitors.find((m) => m.id === selectedMonitorId) ?? null

    return (
        <SceneContent>
            <SceneTitleSection
                name="Uptime"
                description="Monitor URLs and view their recent ping history."
                resourceType={{ type: 'default_icon_type' }}
                actions={<CreateMonitorButton />}
            />
            <LemonTable
                loading={monitorsLoading}
                dataSource={monitors}
                columns={[
                    { title: 'Name', dataIndex: 'name' },
                    { title: 'URL', dataIndex: 'url' },
                    {
                        title: 'Created',
                        dataIndex: 'created_at',
                        render: (_, row: Monitor) => dayjs(row.created_at).fromNow(),
                    },
                    {
                        title: 'Actions',
                        key: 'actions',
                        render: (_, row: Monitor) => (
                            <div className="flex gap-2">
                                <LemonButton type="secondary" size="small" onClick={() => selectMonitor(row.id)}>
                                    View pings
                                </LemonButton>
                                <LemonButton type="secondary" size="small" onClick={() => pingNow(row.id)}>
                                    Ping now
                                </LemonButton>
                            </div>
                        ),
                    },
                ]}
                emptyState="No monitors yet. Create one to start tracking uptime."
            />

            <LemonModal
                isOpen={selectedMonitorId !== null}
                onClose={() => selectMonitor(null)}
                title={selectedMonitor ? `Recent pings: ${selectedMonitor.name}` : 'Pings'}
                width={800}
            >
                <LemonTable
                    loading={pingsLoading}
                    dataSource={pings}
                    columns={[
                        {
                            title: 'When',
                            dataIndex: 'timestamp',
                            render: (_, row: Ping) => dayjs(row.timestamp).fromNow(),
                        },
                        {
                            title: 'Outcome',
                            dataIndex: 'outcome',
                            render: (_, row: Ping) => (
                                <LemonTag type={row.outcome === 'success' ? 'success' : 'danger'}>
                                    {row.outcome}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Status',
                            dataIndex: 'status_code',
                            render: (_, row: Ping) => (row.status_code ? String(row.status_code) : '—'),
                        },
                        {
                            title: 'Latency',
                            dataIndex: 'latency_ms',
                            render: (_, row: Ping) => `${row.latency_ms} ms`,
                        },
                    ]}
                    emptyState="No pings recorded yet."
                />
            </LemonModal>
        </SceneContent>
    )
}

function CreateMonitorButton(): JSX.Element {
    const { isCreateMonitorFormSubmitting } = useValues(uptimeSceneLogic)
    const { setCreateMonitorValue, submitCreateMonitor } = useActions(uptimeSceneLogic)

    return (
        <LemonModal
            trigger={
                <LemonButton type="primary" data-attr="create-monitor">
                    Create monitor
                </LemonButton>
            }
            title="Create monitor"
            footer={
                <LemonButton
                    type="primary"
                    loading={isCreateMonitorFormSubmitting}
                    onClick={() => submitCreateMonitor()}
                >
                    Create
                </LemonButton>
            }
        >
            <Form logic={uptimeSceneLogic} formKey="createMonitor" className="deprecated-space-y-4">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="My website" onChange={(v) => setCreateMonitorValue('name', v)} />
                </LemonField>
                <LemonField name="url" label="URL">
                    <LemonInput placeholder="https://example.com" onChange={(v) => setCreateMonitorValue('url', v)} />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
