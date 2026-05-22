import { useActions, useValues } from 'kea'

import { IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerType, ObservationStatus, ReplayObservation } from '../types'

function StatusTag({ status }: { status: ObservationStatus }): JSX.Element {
    if (status === 'succeeded') {
        return <LemonTag type="success">Succeeded</LemonTag>
    }
    if (status === 'failed') {
        return <LemonTag type="danger">Failed</LemonTag>
    }
    if (status === 'running') {
        return (
            <LemonTag type="warning">
                <Spinner className="mr-1" /> Running
            </LemonTag>
        )
    }
    return <LemonTag type="default">Pending</LemonTag>
}

function ResultPreview({
    scannerType,
    observation,
}: {
    scannerType: ScannerType
    observation: ReplayObservation
}): JSX.Element {
    if (observation.status === 'failed') {
        return (
            <Tooltip title={observation.error_reason || 'Unknown error'}>
                <span className="inline-flex items-center gap-1 text-danger text-sm">
                    <IconWarning /> {observation.error_reason || 'Failed'}
                </span>
            </Tooltip>
        )
    }
    if (observation.status !== 'succeeded' || !observation.result) {
        return <span className="text-muted text-sm">—</span>
    }
    const r = observation.result
    if (scannerType === 'monitor') {
        const verdict = Boolean(r.verdict)
        return (
            <div className="flex flex-col gap-1 max-w-md">
                <LemonTag type={verdict ? 'success' : 'default'}>{verdict ? 'Yes' : 'No'}</LemonTag>
                {typeof r.reasoning === 'string' && <span className="text-muted text-xs truncate">{r.reasoning}</span>}
            </div>
        )
    }
    if (scannerType === 'summarizer') {
        return (
            <div className="flex flex-col max-w-md">
                {typeof r.title === 'string' && <span className="font-semibold text-sm truncate">{r.title}</span>}
                {typeof r.summary === 'string' && <span className="text-muted text-xs line-clamp-2">{r.summary}</span>}
            </div>
        )
    }
    if (scannerType === 'classifier') {
        const tags = Array.isArray(r.tags) ? (r.tags as string[]) : []
        return (
            <div className="flex flex-wrap gap-1 max-w-md">
                {tags.length === 0 ? (
                    <span className="text-muted text-sm">No tags</span>
                ) : (
                    tags.map((t) => (
                        <LemonTag key={t} type="option">
                            {t}
                        </LemonTag>
                    ))
                )}
            </div>
        )
    }
    if (scannerType === 'scorer') {
        const score = typeof r.score === 'number' ? r.score : null
        const label = typeof r.label === 'string' ? r.label : null
        return (
            <div className="flex items-baseline gap-2">
                <span className="font-semibold text-lg tabular-nums">{score ?? '—'}</span>
                {label && <span className="text-muted text-xs">{label}</span>}
            </div>
        )
    }
    if (scannerType === 'indexer') {
        const keywords = Array.isArray(r.keywords) ? (r.keywords as string[]) : []
        return (
            <div className="flex flex-col max-w-md">
                {typeof r.summary === 'string' && <span className="text-sm truncate">{r.summary}</span>}
                {keywords.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                        {keywords.slice(0, 5).map((k) => (
                            <LemonTag key={k} type="option" size="small">
                                {k}
                            </LemonTag>
                        ))}
                        {keywords.length > 5 && <span className="text-muted text-xs">+{keywords.length - 5}</span>}
                    </div>
                )}
            </div>
        )
    }
    return <span className="text-muted text-sm">—</span>
}

export function ScannerObservationsTable({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element {
    const logic = replayScannerLogic({ id: scannerId, tabId })
    const { scanner, observations, observationsLoading } = useValues(logic)
    const { loadObservations } = useActions(logic)

    if (!scanner) {
        return <div className="text-muted">Loading…</div>
    }

    const stats = observations.reduce(
        (acc, o) => {
            acc.total += 1
            if (o.status === 'succeeded') {
                acc.succeeded += 1
            } else if (o.status === 'failed') {
                acc.failed += 1
            } else {
                acc.running += 1
            }
            return acc
        },
        { total: 0, succeeded: 0, failed: 0, running: 0 }
    )
    const successRate = stats.total > 0 ? Math.round((stats.succeeded / stats.total) * 100) : null

    const columns: LemonTableColumns<ReplayObservation> = [
        {
            title: 'Session',
            key: 'session',
            render: (_, obs) => (
                <Link to={urls.replaySingle(obs.session_id)} className="font-mono text-xs text-primary">
                    {obs.session_id.slice(0, 12)}…
                </Link>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, obs) => <StatusTag status={obs.status} />,
        },
        {
            title: 'Result',
            key: 'result',
            render: (_, obs) => <ResultPreview scannerType={scanner.scanner_type} observation={obs} />,
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
            title: 'Model',
            key: 'model',
            render: (_, obs) => <span className="font-mono text-xs text-muted">{obs.model_used || '—'}</span>,
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, obs) => <TZLabel time={obs.created_at} />,
            sorter: (a, b) => a.created_at.localeCompare(b.created_at),
        },
    ]

    return (
        <div className="space-y-4 max-w-6xl">
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
                            {stats.running > 0 && (
                                <div className="text-center">
                                    <div className="font-semibold text-lg">{stats.running}</div>
                                    <div className="text-muted">In flight</div>
                                </div>
                            )}
                        </div>
                    )}
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={() => loadObservations()}
                        loading={observationsLoading}
                    >
                        Refresh
                    </LemonButton>
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
                    <span className="text-muted">
                        No observations yet. Once this scanner runs against matching recordings, results will appear
                        here.
                    </span>
                }
            />
        </div>
    )
}
