import { useActions, useValues } from 'kea'

import { IconRefresh, IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { FilterPill } from '../../components/FilterPill'
import { ObservationResultSummary, ObservationStatusTag } from '../../components/ObservationCard'
import type { ReplayObservationApi } from '../../generated/api.schemas'
import {
    OBSERVATIONS_PAGE_SIZE,
    ObservationStatusValue,
    ObservationTriggeredByValue,
    ObservationVerdictValue,
    replayScannerLogic,
} from '../replayScannerLogic'
import { ScanSessionButton } from './ScanSessionButton'

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

// Chip color by how many versions behind the live scanner an observation ran: latest → oldest.
const VERSION_TAG_TYPES: LemonTagType[] = ['success', 'warning', 'caution', 'danger', 'completion']

function Metric({
    label,
    value,
    valueClass,
}: {
    label: string
    value: number | string
    valueClass?: string
}): JSX.Element {
    return (
        <div className="text-center">
            <div className={`font-semibold text-lg ${valueClass ?? ''}`}>{value}</div>
            <div className="text-muted">{label}</div>
        </div>
    )
}

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

export function ScannerObservationsTable({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = replayScannerLogic({ id: scannerId })
    const {
        observations,
        observationsLoading,
        hasObservationsInFlight,
        observationsPage,
        observationsTotal,
        observationsSort,
        observationStatusFilter,
        observationTriggeredByFilter,
        observationVerdictFilter,
        observationTagFilter,
        hasActiveObservationFilters,
        availableTags,
        observationStats,
        scanner,
        triggeringOnDemandObservation,
        refreshing,
    } = useValues(logic)
    const {
        refreshObservations,
        setObservationsPage,
        setObservationsSort,
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
            render: (_, obs) => <ObservationStatusTag status={obs.status} errorReason={obs.error_reason} />,
        },
        {
            title: 'Result',
            key: 'result',
            render: (_, obs) => (
                <Link to={urls.replayVisionObservation(obs.id)} className="block">
                    <div className="min-w-[18rem] max-w-xl">
                        <ObservationResultSummary observation={obs} />
                    </div>
                </Link>
            ),
            sorter: scannerType === 'scorer' || scannerType === 'monitor' ? true : undefined,
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
            sorter: true,
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
            sorter: true,
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
                    data-attr="vision-observation-view-recording"
                >
                    View recording
                </LemonButton>
            ),
        },
    ]

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-3">
                <p className="text-muted text-sm m-0">
                    Past observations made by this scanner. Each row is one observation.
                </p>
                <div className="ml-auto flex items-center gap-3">
                    <div className="flex items-center gap-2">
                        <ScanSessionButton scannerId={scannerId} />
                        {(observationStats.total > 0 || hasActiveObservationFilters) && (
                            <>
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
                            </>
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
                                onClick={() => refreshObservations()}
                                loading={refreshing}
                                data-attr="vision-observations-refresh"
                            >
                                Refresh
                            </LemonButton>
                        </Tooltip>
                    </div>
                    {observationStats.total > 0 && (
                        <div className="flex gap-4 text-sm">
                            <Metric label="Total" value={observationStats.total} />
                            {observationStats.successRate !== null && (
                                <Metric
                                    label="Success rate"
                                    value={`${observationStats.successRate}%`}
                                    valueClass="text-success"
                                />
                            )}
                            {observationStats.failed > 0 && (
                                <Metric label="Failed" value={observationStats.failed} valueClass="text-danger" />
                            )}
                            {observationStats.ineligible > 0 && (
                                <Metric label="Ineligible" value={observationStats.ineligible} />
                            )}
                            {observationStats.inFlight > 0 && (
                                <Metric label="In flight" value={observationStats.inFlight} />
                            )}
                        </div>
                    )}
                </div>
            </div>
            <LemonTable
                columns={columns}
                dataSource={observations}
                loading={
                    refreshing || triggeringOnDemandObservation || (observationsLoading && observations.length === 0)
                }
                rowKey="id"
                pagination={{
                    controlled: true,
                    pageSize: OBSERVATIONS_PAGE_SIZE,
                    currentPage: observationsPage,
                    entryCount: observationsTotal,
                    onForward: () => setObservationsPage(observationsPage + 1),
                    onBackward: () => setObservationsPage(observationsPage - 1),
                }}
                sorting={observationsSort}
                onSort={(next) => setObservationsSort(next)}
                useURLForSorting={false}
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
