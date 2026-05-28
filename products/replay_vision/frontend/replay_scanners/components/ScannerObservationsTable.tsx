import { useActions, useValues } from 'kea'

import { IconRefresh, IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { ObservationResultSummary, ObservationStatusTag } from '../../components/ObservationCard'
import type { ReplayObservationApi } from '../../generated/api.schemas'
import { replayScannerLogic } from '../replayScannerLogic'

export function ScannerObservationsTable({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element {
    const logic = replayScannerLogic({ id: scannerId, tabId })
    const { observations, observationsLoading, hasObservationsInFlight } = useValues(logic)
    const { loadObservations } = useActions(logic)

    const stats = observations.reduce(
        (acc, o) => {
            acc.total += 1
            if (o.status === 'succeeded') {
                acc.succeeded += 1
            } else if (o.status === 'failed') {
                acc.failed += 1
            } else if (o.status === 'ineligible') {
                acc.ineligible += 1
            } else {
                acc.inFlight += 1
            }
            return acc
        },
        { total: 0, succeeded: 0, failed: 0, ineligible: 0, inFlight: 0 }
    )
    // Success rate excludes ineligible — those weren't scanner failures, they were skipped at the gate.
    const scored = stats.succeeded + stats.failed
    const successRate = scored > 0 ? Math.round((stats.succeeded / scored) * 100) : null

    const columns: LemonTableColumns<ReplayObservationApi> = [
        {
            title: 'Session',
            key: 'session',
            width: 300,
            render: (_, obs) => (
                <Link
                    to={urls.replayVisionObservation(obs.id)}
                    className="font-mono text-xs text-primary truncate block"
                >
                    {obs.session_id}
                </Link>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, obs) => <ObservationStatusTag status={obs.status} />,
        },
        {
            title: 'Result',
            key: 'result',
            render: (_, obs) => (
                <div className="min-w-[18rem] max-w-xl">
                    <ObservationResultSummary observation={obs} />
                </div>
            ),
        },
        {
            title: 'Triggered by',
            key: 'triggered_by',
            render: (_, obs) => (
                <LemonTag type={obs.triggered_by === 'on_demand' ? 'highlight' : 'default'}>
                    {obs.triggered_by === 'on_demand' ? 'On demand' : 'Schedule'}
                </LemonTag>
            ),
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, obs) => <TZLabel time={obs.created_at} />,
            sorter: (a, b) => a.created_at.localeCompare(b.created_at),
        },
        {
            title: '',
            key: 'actions',
            width: 1,
            render: (_, obs) => (
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRewindPlay />}
                    to={urls.replaySingle(obs.session_id)}
                    className="whitespace-nowrap"
                >
                    View recording
                </LemonButton>
            ),
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex items-start justify-between gap-4">
                <p className="text-muted text-sm m-0">
                    Past applications of this scanner to session recordings. Each row is one observation.
                </p>
                <div className="flex items-center gap-4">
                    {stats.total > 0 && (
                        <div className="flex gap-4 text-sm">
                            <div className="text-center">
                                <div className="font-semibold text-lg">{stats.total}</div>
                                <div className="text-muted">Total</div>
                            </div>
                            {successRate !== null && (
                                <div className="text-center">
                                    <div className="font-semibold text-lg text-success">{successRate}%</div>
                                    <div className="text-muted">Success rate</div>
                                </div>
                            )}
                            {stats.failed > 0 && (
                                <div className="text-center">
                                    <div className="font-semibold text-lg text-danger">{stats.failed}</div>
                                    <div className="text-muted">Failed</div>
                                </div>
                            )}
                            {stats.ineligible > 0 && (
                                <div className="text-center">
                                    <div className="font-semibold text-lg">{stats.ineligible}</div>
                                    <div className="text-muted">Ineligible</div>
                                </div>
                            )}
                            {stats.inFlight > 0 && (
                                <div className="text-center">
                                    <div className="font-semibold text-lg">{stats.inFlight}</div>
                                    <div className="text-muted">In flight</div>
                                </div>
                            )}
                        </div>
                    )}
                    <Tooltip
                        title={
                            hasObservationsInFlight
                                ? 'Auto-refreshing while observations are in flight'
                                : 'Refresh observations'
                        }
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconRefresh />}
                            onClick={() => loadObservations()}
                            loading={observationsLoading}
                        >
                            Refresh
                        </LemonButton>
                    </Tooltip>
                </div>
            </div>
            <LemonTable
                columns={columns}
                dataSource={observations}
                loading={observationsLoading}
                rowKey="id"
                pagination={{ pageSize: 50 }}
                nouns={['observation', 'observations']}
                emptyState={
                    <div className="p-6 text-center text-muted">
                        No observations yet. Observations appear here once the scanner runs on a schedule, or when you
                        observe a recording from the session replay page.
                    </div>
                }
            />
        </div>
    )
}
