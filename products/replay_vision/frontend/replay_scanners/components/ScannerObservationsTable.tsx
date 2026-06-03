import { useActions, useValues } from 'kea'

import { IconRefresh, IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { FilterPill } from '../../components/FilterPill'
import { ObservationResultSummary, ObservationStatusTag } from '../../components/ObservationCard'
import type { ReplayObservationApi } from '../../generated/api.schemas'
import { readScore, readVerdict } from '../../utils/observation'
import {
    ObservationStatusValue,
    ObservationTriggeredByValue,
    ObservationVerdictValue,
    replayScannerLogic,
} from '../replayScannerLogic'
import { ScannerOverview } from './ScannerOverview'

const STATUS_OPTIONS: { value: ObservationStatusValue; label: string }[] = [
    { value: 'succeeded', label: 'Succeeded' },
    { value: 'failed', label: 'Failed' },
    { value: 'ineligible', label: 'Ineligible' },
    { value: 'running', label: 'Running' },
    { value: 'pending', label: 'Pending' },
]

const TRIGGERED_BY_OPTIONS: { value: ObservationTriggeredByValue; label: string }[] = [
    { value: 'on_demand', label: 'On demand' },
    { value: 'schedule', label: 'Schedule' },
]

const VERDICT_OPTIONS: { value: ObservationVerdictValue; label: string }[] = [
    { value: 'yes', label: 'Yes' },
    { value: 'no', label: 'No' },
    { value: 'inconclusive', label: 'Inconclusive' },
]

// Nulls (no model output) sort last regardless of direction.
function compareByScore(a: ReplayObservationApi, b: ReplayObservationApi): number {
    const sa = readScore(a)
    const sb = readScore(b)
    if (sa === null || sb === null) {
        return sa === sb ? 0 : sa === null ? 1 : -1
    }
    return sa - sb
}

function compareByVerdict(a: ReplayObservationApi, b: ReplayObservationApi): number {
    const va = readVerdict(a)
    const vb = readVerdict(b)
    if (va === vb) {
        return 0
    }
    if (va === null || vb === null) {
        return va === null ? 1 : -1
    }
    return va ? -1 : 1
}

// Rows with no snapshot (rendered as "—") sort last regardless of direction, matching compareByScore/Verdict.
function compareByVersion(a: ReplayObservationApi, b: ReplayObservationApi): number {
    const va = a.scanner_snapshot?.scanner_version ?? null
    const vb = b.scanner_snapshot?.scanner_version ?? null
    if (va === null || vb === null) {
        return va === vb ? 0 : va === null ? 1 : -1
    }
    return va - vb
}

// Chip color by how many versions behind the live scanner an observation ran: latest → oldest.
const VERSION_TAG_TYPES: LemonTagType[] = ['success', 'warning', 'caution', 'danger', 'completion']

function versionTag(
    obsVersion: number | null | undefined,
    currentVersion: number | null | undefined
): { type: LemonTagType; label: string; tooltip: string } | null {
    if (obsVersion == null) {
        return null
    }
    const label = `v${obsVersion}`
    if (currentVersion == null) {
        return { type: 'muted', label, tooltip: `Ran with scanner version ${obsVersion}` }
    }
    const age = Math.max(0, currentVersion - obsVersion)
    const type = VERSION_TAG_TYPES[Math.min(age, VERSION_TAG_TYPES.length - 1)]
    const tooltip =
        age === 0 ? `Current version (v${currentVersion})` : `${age} version(s) behind current (v${currentVersion})`
    return { type, label, tooltip }
}

export function ScannerObservationsTable({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element {
    const logic = replayScannerLogic({ id: scannerId, tabId })
    const {
        observationsLoading,
        hasObservationsInFlight,
        filteredObservations,
        observationStatusFilter,
        observationTriggeredByFilter,
        observationVerdictFilter,
        observationTagFilter,
        hasActiveObservationFilters,
        availableTags,
        observationStats,
        scanner,
    } = useValues(logic)
    const {
        loadObservations,
        setObservationStatusFilter,
        setObservationTriggeredByFilter,
        setObservationVerdictFilter,
        setObservationTagFilter,
        clearObservationFilters,
    } = useActions(logic)
    const scannerType = scanner?.scanner_type
    const tagFilterOptions = availableTags.map((tag) => ({ value: tag, label: tag }))

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
            sorter:
                scannerType === 'scorer' ? compareByScore : scannerType === 'monitor' ? compareByVerdict : undefined,
        },
        {
            title: 'Version',
            key: 'version',
            render: (_, obs) => {
                const tag = versionTag(obs.scanner_snapshot?.scanner_version, scanner?.scanner_version)
                if (!tag) {
                    return <span className="text-muted">—</span>
                }
                return (
                    <Tooltip title={tag.tooltip}>
                        <LemonTag type={tag.type} className="font-mono">
                            {tag.label}
                        </LemonTag>
                    </Tooltip>
                )
            },
            sorter: compareByVersion,
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
            <ScannerOverview scannerId={scannerId} tabId={tabId} />
            <div className="flex items-start justify-between gap-4">
                <p className="text-muted text-sm m-0">
                    Past applications of this scanner to session recordings. Each row is one observation.
                </p>
                <div className="flex items-center gap-4">
                    {observationStats.total > 0 && (
                        <div className="flex gap-4 text-sm">
                            <div className="text-center">
                                <div className="font-semibold text-lg">{observationStats.total}</div>
                                <div className="text-muted">Total</div>
                            </div>
                            {observationStats.successRate !== null && (
                                <div className="text-center">
                                    <div className="font-semibold text-lg text-success">
                                        {observationStats.successRate}%
                                    </div>
                                    <div className="text-muted">Success rate</div>
                                </div>
                            )}
                            {observationStats.failed > 0 && (
                                <div className="text-center">
                                    <div className="font-semibold text-lg text-danger">{observationStats.failed}</div>
                                    <div className="text-muted">Failed</div>
                                </div>
                            )}
                            {observationStats.ineligible > 0 && (
                                <div className="text-center">
                                    <div className="font-semibold text-lg">{observationStats.ineligible}</div>
                                    <div className="text-muted">Ineligible</div>
                                </div>
                            )}
                            {observationStats.inFlight > 0 && (
                                <div className="text-center">
                                    <div className="font-semibold text-lg">{observationStats.inFlight}</div>
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
            {observationStats.total > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                    <FilterPill<ObservationStatusValue>
                        label="Status"
                        options={STATUS_OPTIONS}
                        value={observationStatusFilter}
                        onChange={setObservationStatusFilter}
                    />
                    <FilterPill<ObservationTriggeredByValue>
                        label="Triggered by"
                        options={TRIGGERED_BY_OPTIONS}
                        value={observationTriggeredByFilter}
                        onChange={setObservationTriggeredByFilter}
                    />
                    {scannerType === 'monitor' && (
                        <FilterPill<ObservationVerdictValue>
                            label="Verdict"
                            options={VERDICT_OPTIONS}
                            value={observationVerdictFilter}
                            onChange={setObservationVerdictFilter}
                        />
                    )}
                    {scannerType === 'classifier' && tagFilterOptions.length > 0 && (
                        <FilterPill<string>
                            label="Tag"
                            options={tagFilterOptions}
                            value={observationTagFilter}
                            onChange={setObservationTagFilter}
                        />
                    )}
                    {hasActiveObservationFilters && (
                        <LemonButton type="tertiary" size="small" onClick={() => clearObservationFilters()}>
                            Clear filters
                        </LemonButton>
                    )}
                </div>
            )}
            <LemonTable
                columns={columns}
                dataSource={filteredObservations}
                loading={observationsLoading}
                rowKey="id"
                pagination={{ pageSize: 50 }}
                nouns={['observation', 'observations']}
                emptyState={
                    <div className="p-6 text-center text-muted">
                        {hasActiveObservationFilters
                            ? 'No observations match your filters.'
                            : "No observations yet. They'll appear here once the scanner fires on its schedule, or when you manually trigger one from a session recording."}
                    </div>
                }
            />
        </div>
    )
}
