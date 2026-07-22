import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconEye, IconPlay } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { recordingsQueryToUniversalFilters } from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { ReplayFiltersTab } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import {
    SessionRecordingPlaylistLogicProps,
    getDefaultFilters,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { SessionRecordingType } from '~/types'

import { ObservationStatusTag } from '../../components/ObservationCard'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { IN_PROGRESS_STATUSES, scannerRunTabLogic } from '../scannerRunTabLogic'

/** Manual entry: scan one session by pasting its recording ID. */
function ScanBySessionId({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner, triggeringOnDemandObservation, onDemandObservationSuccessCount } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const { triggerOnDemandObservation } = useActions(replayScannerLogic({ id: scannerId }))
    const [sessionId, setSessionId] = useState('')
    const lastSeenSuccessCount = useRef(onDemandObservationSuccessCount)
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)

    useEffect(() => {
        if (onDemandObservationSuccessCount > lastSeenSuccessCount.current) {
            lastSeenSuccessCount.current = onDemandObservationSuccessCount
            setSessionId('')
        }
    }, [onDemandObservationSuccessCount])

    const trimmed = sessionId.trim()
    const submit = (): void => {
        if (!trimmed || triggeringOnDemandObservation) {
            return
        }
        triggerOnDemandObservation(trimmed)
    }

    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
            <div>
                <h3 className="text-sm font-medium mb-1">Scan a session by ID</h3>
                <p className="text-muted text-sm m-0">
                    Run this scanner against a specific session recording right now, without waiting for the schedule.
                    Paste the recording's session ID below.
                </p>
            </div>
            <div className="flex items-center gap-2">
                <LemonInput
                    value={sessionId}
                    onChange={setSessionId}
                    onPressEnter={submit}
                    placeholder="Session ID"
                    fullWidth
                    data-attr="vision-scanner-scan-session-input"
                />
                <LemonButton
                    type="primary"
                    icon={<IconPlay />}
                    onClick={submit}
                    loading={triggeringOnDemandObservation}
                    disabledReason={editDisabledReason ?? (!trimmed ? 'Paste a session ID first' : undefined)}
                    data-attr="vision-scanner-scan-session-submit"
                >
                    Scan recording
                </LemonButton>
            </div>
        </div>
    )
}

function RecordingsList({ scannerId }: { scannerId: string }): JSX.Element {
    const { filters, totalFiltersCount, sessionRecordings, sessionRecordingsResponseLoading, hasNext } =
        useValues(sessionRecordingsPlaylistLogic)
    const { setFilters, resetFilters, maybeLoadSessionRecordings } = useActions(sessionRecordingsPlaylistLogic)
    const { observationBySession, pendingId, refreshingObservations, bulkScanning } = useValues(
        scannerRunTabLogic({ scannerId })
    )
    const { setVisibleSessionIds, startScan, startBulkScan } = useActions(scannerRunTabLogic({ scannerId }))
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)

    // Sync the playlist's visible rows into the logic, which owns the observation lookup and polling.
    const visibleIdsKey = sessionRecordings.map((recording) => recording.id).join(',')
    useEffect(() => {
        setVisibleSessionIds(visibleIdsKey ? visibleIdsKey.split(',') : [])
    }, [visibleIdsKey, setVisibleSessionIds])

    const columns: LemonTableColumns<SessionRecordingType> = [
        {
            title: 'Session',
            key: 'session',
            width: 300,
            render: (_, recording) => (
                <Link to={urls.replaySingle(recording.id)} className="font-mono text-xs text-primary truncate block">
                    {recording.id}
                </Link>
            ),
        },
        {
            title: 'When',
            dataIndex: 'start_time',
            render: (start_time) => (start_time ? <TZLabel time={String(start_time)} /> : <span>—</span>),
            sorter: (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime(),
        },
        {
            title: 'Duration',
            dataIndex: 'recording_duration',
            render: (duration) => <span className="tabular-nums">{humanFriendlyDuration(Number(duration))}</span>,
            sorter: (a, b) => a.recording_duration - b.recording_duration,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, recording) => {
                const observation = observationBySession[recording.id]
                if (observation) {
                    return <ObservationStatusTag status={observation.status} />
                }
                if (pendingId === recording.id) {
                    return <ObservationStatusTag status="running" />
                }
                return <span className="text-muted italic">Not scanned</span>
            },
        },
        {
            title: '',
            key: 'scan',
            // Fixed width so Scan recording / View observation occupy the same width as the cell swaps.
            width: 184,
            render: (_, recording) => {
                const observation = observationBySession[recording.id]
                const settled = observation && !IN_PROGRESS_STATUSES.has(observation.status)
                // In-flight or queued — the Status pill carries the spinner, so here we just disable the button.
                const scanning =
                    (observation && IN_PROGRESS_STATUSES.has(observation.status)) || pendingId === recording.id
                let content: JSX.Element
                if (settled) {
                    // Observation ready → link to the result.
                    content = (
                        <LemonButton
                            fullWidth
                            center
                            size="small"
                            type="secondary"
                            icon={<IconEye />}
                            to={urls.replayVisionObservation(observation.id)}
                            data-attr="vision-run-view-observation"
                        >
                            View observation
                        </LemonButton>
                    )
                } else {
                    content = (
                        <LemonButton
                            fullWidth
                            center
                            size="small"
                            type="secondary"
                            icon={<IconPlay />}
                            disabledReason={
                                editDisabledReason ??
                                (scanning
                                    ? 'Scan in progress…'
                                    : pendingId && pendingId !== recording.id
                                      ? 'Another scan is starting…'
                                      : undefined)
                            }
                            onClick={() => startScan(recording.id)}
                            data-attr="vision-run-scan-recording"
                        >
                            Scan recording
                        </LemonButton>
                    )
                }
                return <div className="w-44">{content}</div>
            },
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="rounded border overflow-hidden">
                <ReplayFiltersTab
                    resetFilters={resetFilters}
                    filters={filters}
                    setFilters={setFilters}
                    totalFiltersCount={totalFiltersCount}
                    allowReplayHogQLFilters={false}
                    compactActions
                />
            </div>
            <LemonTable
                columns={columns}
                dataSource={sessionRecordings}
                loading={sessionRecordingsResponseLoading || refreshingObservations}
                rowKey="id"
                emptyState="No recordings match these filters."
                data-attr="vision-run-recordings-table"
                bulkSelection={{
                    noun: ['recording', 'recordings'],
                    // Only not-yet-scanned rows are selectable — a scanned or in-flight session has nothing
                    // to (re)scan, matching the per-row button that swaps to "View observation".
                    isRowSelectable: (recording) =>
                        observationBySession[recording.id] || pendingId === recording.id
                            ? { disabledReason: 'Already scanned' }
                            : true,
                    renderActions: ({ selectedKeys, selectedCount, clearSelection }) => (
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlay />}
                            loading={bulkScanning}
                            disabledReason={editDisabledReason}
                            onClick={() => {
                                startBulkScan(selectedKeys as string[])
                                clearSelection()
                            }}
                            data-attr="vision-run-bulk-scan"
                        >
                            Scan {selectedCount} selected
                        </LemonButton>
                    ),
                }}
            />
            {hasNext && (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        onClick={() => maybeLoadSessionRecordings('older')}
                        loading={sessionRecordingsResponseLoading}
                        data-attr="vision-run-load-more"
                    >
                        Load more
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

/** Browse and filter recordings, then fire this scanner against any of them. */
function ScanFromRecordings({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    // Seed the browser with the scanner's own scan conditions so it previews the recordings this scanner
    // actually runs against, not just the latest recordings. Only the condition dimensions
    // (events/actions/properties/duration/test accounts) live on the scanner query, so overlay those onto
    // the default recent-recordings date range and sort order. The user can still widen or clear the filters.
    const scannerConditions = recordingsQueryToUniversalFilters(scanner?.query)
    const logicProps: SessionRecordingPlaylistLogicProps = {
        logicKey: `vision-run-${scannerId}`,
        updateSearchParams: false,
        filters: { ...getDefaultFilters(), ...scannerConditions },
    }
    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
            <div>
                <h3 className="text-sm font-medium mb-1">Pick from your recordings</h3>
                <p className="text-muted text-sm m-0">
                    Filter your session recordings and run this scanner against any of them. Scan one at a time, or
                    select several and scan them together. Each scan produces one observation.
                </p>
            </div>
            <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
                <RecordingsList scannerId={scannerId} />
            </BindLogic>
        </div>
    )
}

function OrDivider(): JSX.Element {
    return (
        <div className="flex items-center justify-center gap-4 text-muted text-base font-semibold uppercase tracking-wide">
            <div className="w-24 border-t-2" />
            or
            <div className="w-24 border-t-2" />
        </div>
    )
}

export function ScannerRunTab({ scannerId }: { scannerId: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-8">
            <ScanBySessionId scannerId={scannerId} />
            <OrDivider />
            <ScanFromRecordings scannerId={scannerId} />
        </div>
    )
}
