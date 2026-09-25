import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { LogsSourceApi } from 'products/logs/frontend/generated/api.schemas'

import { logsSourcesLogic } from './logsSourcesLogic'
import { logsSourceStatusTag } from './logsSourceStatus'

export function LogsSourcesTable(): JSX.Element {
    const {
        sources,
        sourcesLoading,
        sourcesLoadFailed,
        healthBySourceId,
        healthUnavailable,
        togglePendingId,
        deletePendingId,
    } = useValues(logsSourcesLogic)
    const { openWizard, openWizardForSource, setSourceEnabled, deleteSource, loadSources } =
        useActions(logsSourcesLogic)

    const confirmDelete = (source: LogsSourceApi): void => {
        LemonDialog.open({
            title: `Delete ${source.name}?`,
            description:
                "Logs sent to this source's endpoint will no longer be stored. The Firehose stream in your AWS account keeps running until you delete it there.",
            primaryButton: {
                children: 'Delete source',
                status: 'danger',
                onClick: () => deleteSource(source.id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="space-y-2">
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={openWizard}
                    data-attr="logs-source-add"
                >
                    Add source
                </LemonButton>
            </div>
            {sourcesLoadFailed && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: loadSources,
                        loading: sourcesLoading,
                        'data-attr': 'logs-sources-retry-load',
                    }}
                >
                    Couldn't load your sources. Try again, and if it keeps happening contact support.
                </LemonBanner>
            )}
            <LemonTable
                dataSource={sources}
                loading={sourcesLoading && sources.length === 0}
                rowKey="id"
                emptyState={
                    sourcesLoadFailed
                        ? 'No sources to show.'
                        : 'No sources yet. Add one to stream CloudWatch logs into this environment.'
                }
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, source) => <strong>{source.name}</strong>,
                    },
                    {
                        title: 'Region',
                        key: 'region',
                        render: (_, source) => (
                            <span className="font-mono text-sm whitespace-nowrap">{source.config.region}</span>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, source) => {
                            const { label, type } = logsSourceStatusTag(
                                healthBySourceId[source.id]?.status,
                                healthUnavailable
                            )
                            return <LemonTag type={type}>{label}</LemonTag>
                        },
                    },
                    {
                        title: 'Last received',
                        key: 'last_received',
                        render: (_, source) => {
                            const lastReceived = healthBySourceId[source.id]?.last_received_at
                            return lastReceived ? (
                                <TZLabel time={lastReceived} />
                            ) : (
                                <span className="text-muted">Never</span>
                            )
                        },
                    },
                    {
                        title: 'Enabled',
                        key: 'enabled',
                        width: 0,
                        render: (_, source) => (
                            <LemonSwitch
                                checked={source.enabled ?? true}
                                onChange={(checked) => setSourceEnabled(source.id, checked)}
                                disabledReason={togglePendingId === source.id ? 'Saving your change' : undefined}
                                data-attr="logs-source-enabled-switch"
                            />
                        ),
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, source) => (
                            <div className="flex gap-1">
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    onClick={() => openWizardForSource(source.id)}
                                    data-attr="logs-source-open-setup"
                                >
                                    View setup
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    status="danger"
                                    onClick={() => confirmDelete(source)}
                                    loading={deletePendingId === source.id}
                                    data-attr="logs-source-delete"
                                >
                                    Delete
                                </LemonButton>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
