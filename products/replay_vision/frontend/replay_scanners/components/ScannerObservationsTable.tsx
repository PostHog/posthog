import { useActions, useValues } from 'kea'

import { IconPlay, IconRefresh, IconRewindPlay, IconThumbsDownFilled, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

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
        observationSubjectFilter,
        hasActiveObservationFilters,
        availableTags,
        observationStats,
        scanner,
        triggeringOnDemandObservation,
        retryingObservationIds,
    } = useValues(logic)
    const {
        refreshObservations,
        retryObservation,
        setObservationsPage,
        setObservationsSort,
        setObservationStatusFilter,
        setObservationTriggeredByFilter,
        setObservationVerdictFilter,
        setObservationTagFilter,
        setObservationSubjectFilter,
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
            title: 'Recording subject',
            key: 'recording_subject',
            sorter: true,
            render: (_, obs) =>
                obs.recording_subject_email ? (
                    <Tooltip title={obs.distinct_id ?? undefined}>
                        <span className="truncate block max-w-[16rem]">{obs.recording_subject_email}</span>
                    </Tooltip>
                ) : obs.distinct_id ? (
                    <span className="font-mono text-xs text-muted truncate block max-w-[16rem]">{obs.distinct_id}</span>
                ) : (
                    <span className="text-muted">—</span>
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
            title: 'Feedback',
            key: 'feedback',
            sorter: true,
            render: (_, obs) => {
                const label = obs.label
                const to = urls.replayVisionObservation(obs.id)
                if (!label) {
                    return (
                        <Link to={to} className="block text-muted">
                            —
                        </Link>
                    )
                }
                const feedback = !label.is_correct ? label.feedback : null
                const content = (
                    <span className="inline-flex items-center">
                        {label.is_correct ? (
                            <IconThumbsUpFilled className="text-success" aria-label="Thumbs up" />
                        ) : (
                            <IconThumbsDownFilled className="text-danger" aria-label="Thumbs down" />
                        )}
                    </span>
                )
                return (
                    <Link to={to} className="block">
                        {feedback ? <Tooltip title={feedback}>{content}</Tooltip> : content}
                    </Link>
                )
            },
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
                <div className="flex gap-1">
                    {obs.status === 'failed' && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={<IconRefresh />}
                                onClick={() => retryObservation(obs.id)}
                                loading={retryingObservationIds.includes(obs.id)}
                                className="whitespace-nowrap"
                                data-attr="vision-observation-retry"
                            >
                                Retry
                            </LemonButton>
                        </AccessControlAction>
                    )}
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
                </div>
            ),
        },
    ]

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-3">
                <h3 className="font-semibold text-base m-0">Observation history</h3>
                <div className="ml-auto flex items-center gap-3">
                    <div className="flex items-center gap-2">
                        {(observationStats.total > 0 || hasActiveObservationFilters) && (
                            <>
                                <LemonInput
                                    type="search"
                                    size="small"
                                    placeholder="Recording subject email"
                                    value={observationSubjectFilter}
                                    onChange={setObservationSubjectFilter}
                                    className="w-56"
                                />
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
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    onClick={() => clearObservationFilters()}
                                    disabledReason={hasActiveObservationFilters ? undefined : 'No active filters'}
                                >
                                    Clear filters
                                </LemonButton>
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
                                loading={observationsLoading}
                                data-attr="vision-observations-refresh"
                            >
                                Refresh
                            </LemonButton>
                        </Tooltip>
                    </div>
                    {/* Always rendered (0 / N/A when empty) so a zero-match filter doesn't drop the metrics and shift the controls. */}
                    <div className="flex gap-4 text-sm">
                        <Metric label="Total" value={observationStats.total} />
                        <Metric
                            label="Success rate"
                            value={observationStats.successRate !== null ? `${observationStats.successRate}%` : 'N/A'}
                            valueClass={observationStats.successRate !== null ? 'text-success' : undefined}
                        />
                        <Metric
                            label="Failed"
                            value={observationStats.failed}
                            valueClass={observationStats.failed > 0 ? 'text-danger' : undefined}
                        />
                        <Metric label="Ineligible" value={observationStats.ineligible} />
                        <Metric label="In flight" value={observationStats.inFlight} />
                    </div>
                </div>
            </div>
            <LemonTable
                columns={columns}
                dataSource={observations}
                loading={triggeringOnDemandObservation || observationsLoading}
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
                // The URL scheme can't express "no sort", so a third header click would snap back with duplicate fetches.
                noSortingCancellation
                nouns={['observation', 'observations']}
                emptyState={
                    hasActiveObservationFilters ? (
                        <div className="p-6 text-center text-muted">No observations match your filters.</div>
                    ) : (
                        <div className="p-6 flex flex-col items-center gap-3 text-center">
                            <div className="text-muted">
                                No observations yet. They'll appear here once the scanner fires on its schedule — or
                                scan a recording right now.
                            </div>
                            <LemonButton
                                type="primary"
                                icon={<IconPlay />}
                                to={`${urls.replayVision(scannerId)}?tab=on-demand`}
                                data-attr="vision-observations-empty-scan-now"
                            >
                                Scan a recording now
                            </LemonButton>
                        </div>
                    )
                }
            />
        </div>
    )
}
