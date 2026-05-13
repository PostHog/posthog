import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyNumber } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { Monitor, Ping, SuggestedUrl, uptimeSceneLogic } from './uptimeSceneLogic'

export const scene: SceneExport = {
    component: UptimeScene,
    logic: uptimeSceneLogic,
}

export function UptimeScene(): JSX.Element {
    const { monitors, monitorsLoading, suggestedUrls, selectedMonitorId, pings, pingsLoading } =
        useValues(uptimeSceneLogic)
    const { selectMonitor, pingNow, setCreateModalOpen, setSuggestModalOpen } = useActions(uptimeSceneLogic)

    const selectedMonitor = monitors.find((m) => m.id === selectedMonitorId) ?? null
    const hasSuggestions = suggestedUrls.length > 0

    return (
        <SceneContent>
            <SceneTitleSection
                name="Uptime"
                description="Monitor URLs and view their recent ping history."
                resourceType={{ type: 'default_icon_type' }}
                actions={
                    <div className="flex gap-2">
                        {hasSuggestions && (
                            <LemonButton
                                type="secondary"
                                data-attr="open-suggest-urls"
                                onClick={() => setSuggestModalOpen(true)}
                            >
                                Add from traffic ({suggestedUrls.length})
                            </LemonButton>
                        )}
                        <LemonButton type="primary" data-attr="create-monitor" onClick={() => setCreateModalOpen(true)}>
                            Create monitor
                        </LemonButton>
                    </div>
                }
            />
            <CreateMonitorModal />
            <SuggestUrlsModal />
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
                emptyState={
                    hasSuggestions ? (
                        <div className="flex flex-col items-center gap-2 py-4">
                            <div>
                                We spotted <strong>{suggestedUrls.length}</strong> URL
                                {suggestedUrls.length === 1 ? '' : 's'} in your traffic. Pick which to monitor.
                            </div>
                            <LemonButton type="primary" onClick={() => setSuggestModalOpen(true)}>
                                Add from traffic
                            </LemonButton>
                        </div>
                    ) : (
                        'No monitors yet. Create one to start tracking uptime.'
                    )
                }
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

function CreateMonitorModal(): JSX.Element {
    const { createModalOpen, isCreateMonitorFormSubmitting, topSuggestedUrls } = useValues(uptimeSceneLogic)
    const { setCreateMonitorValue, submitCreateMonitor, setCreateModalOpen } = useActions(uptimeSceneLogic)

    return (
        <LemonModal
            isOpen={createModalOpen}
            onClose={() => setCreateModalOpen(false)}
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
                {topSuggestedUrls.length > 0 && (
                    <div className="flex flex-col gap-2">
                        <div className="text-sm text-secondary">Suggested from your traffic</div>
                        <div className="flex flex-wrap gap-2">
                            {topSuggestedUrls.map((s: SuggestedUrl) => (
                                <LemonButton
                                    key={s.url}
                                    type="secondary"
                                    size="small"
                                    onClick={() => {
                                        setCreateMonitorValue('url', s.url)
                                        setCreateMonitorValue('name', s.host)
                                    }}
                                    tooltip={`${humanFriendlyNumber(s.event_count)} pageviews, ${s.unique_paths} paths`}
                                >
                                    {s.host}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                )}
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

function SuggestUrlsModal(): JSX.Element {
    const { suggestModalOpen, suggestedUrls, suggestedUrlsLoading, selectedSuggestions } = useValues(uptimeSceneLogic)
    const { setSuggestModalOpen, toggleSuggestion, clearSelectedSuggestions, bulkAddSelected } =
        useActions(uptimeSceneLogic)

    const selectedSet = new Set(selectedSuggestions)
    const allSelected = suggestedUrls.length > 0 && selectedSuggestions.length === suggestedUrls.length

    return (
        <LemonModal
            isOpen={suggestModalOpen}
            onClose={() => setSuggestModalOpen(false)}
            title="Add monitors from traffic"
            description="Pick URLs detected from $pageview events. Already-monitored hosts are excluded."
            width={760}
            footer={
                <div className="flex w-full items-center justify-between">
                    <div className="text-sm text-secondary">
                        {selectedSuggestions.length} of {suggestedUrls.length} selected
                    </div>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={() => setSuggestModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={selectedSuggestions.length === 0 ? 'Select at least one URL' : undefined}
                            onClick={() => bulkAddSelected()}
                        >
                            Add {selectedSuggestions.length || ''} monitor
                            {selectedSuggestions.length === 1 ? '' : 's'}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonTable
                loading={suggestedUrlsLoading}
                dataSource={suggestedUrls}
                rowKey="url"
                columns={[
                    {
                        title: (
                            <LemonCheckbox
                                checked={allSelected}
                                onChange={() => {
                                    if (allSelected) {
                                        clearSelectedSuggestions()
                                    } else {
                                        suggestedUrls.forEach((s: SuggestedUrl) => {
                                            if (!selectedSet.has(s.url)) {
                                                toggleSuggestion(s.url)
                                            }
                                        })
                                    }
                                }}
                            />
                        ),
                        key: 'select',
                        width: 0,
                        render: (_, row: SuggestedUrl) => (
                            <LemonCheckbox
                                checked={selectedSet.has(row.url)}
                                onChange={() => toggleSuggestion(row.url)}
                            />
                        ),
                    },
                    {
                        title: 'URL',
                        dataIndex: 'url',
                        render: (_, row: SuggestedUrl) => (
                            <div className="flex flex-col">
                                <span className="font-medium">{row.host}</span>
                                <span className="text-xs text-secondary">{row.url}</span>
                            </div>
                        ),
                    },
                    {
                        title: 'Pageviews',
                        dataIndex: 'event_count',
                        sorter: (a: SuggestedUrl, b: SuggestedUrl) => a.event_count - b.event_count,
                        render: (_, row: SuggestedUrl) => humanFriendlyNumber(row.event_count),
                    },
                    {
                        title: 'Unique paths',
                        dataIndex: 'unique_paths',
                        sorter: (a: SuggestedUrl, b: SuggestedUrl) => a.unique_paths - b.unique_paths,
                    },
                    {
                        title: 'Last seen',
                        dataIndex: 'last_seen',
                        sorter: (a: SuggestedUrl, b: SuggestedUrl) =>
                            dayjs(a.last_seen).valueOf() - dayjs(b.last_seen).valueOf(),
                        render: (_, row: SuggestedUrl) => dayjs(row.last_seen).fromNow(),
                    },
                ]}
                emptyState="No suggestions yet. Once we see $pageview events, pingable hosts will appear here."
            />
        </LemonModal>
    )
}
