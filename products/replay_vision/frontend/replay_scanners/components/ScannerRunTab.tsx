import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconEye, IconPlay } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { ReplayFiltersTab } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, SessionRecordingType } from '~/types'

import { ObservationStatusTag } from '../../components/ObservationCard'
import { visionScannersObservationsList } from '../../generated/api'
import type { ReplayObservationApi } from '../../generated/api.schemas'
import { replayScannerLogic } from '../replayScannerLogic'

type RowObservation = { id: string; status: ReplayObservationApi['status'] }
const IN_PROGRESS_STATUSES = new Set<string>(['pending', 'running'])

/** Manual entry: scan one session by pasting its recording ID. */
function ScanBySessionId({ scannerId }: { scannerId: string }): JSX.Element {
    const { triggeringOnDemandObservation, onDemandObservationSuccessCount } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const { triggerOnDemandObservation } = useActions(replayScannerLogic({ id: scannerId }))
    const [sessionId, setSessionId] = useState('')
    const lastSeenSuccessCount = useRef(onDemandObservationSuccessCount)

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
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        icon={<IconPlay />}
                        onClick={submit}
                        loading={triggeringOnDemandObservation}
                        disabledReason={!trimmed ? 'Paste a session ID first' : undefined}
                        data-attr="vision-scanner-scan-session-submit"
                    >
                        Scan recording
                    </LemonButton>
                </AccessControlAction>
            </div>
        </div>
    )
}

function RecordingsList({ scannerId }: { scannerId: string }): JSX.Element {
    const { filters, totalFiltersCount, sessionRecordings, sessionRecordingsResponseLoading, hasNext } =
        useValues(sessionRecordingsPlaylistLogic)
    const { setFilters, resetFilters, maybeLoadSessionRecordings } = useActions(sessionRecordingsPlaylistLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { triggeringOnDemandObservation, onDemandObservationSuccessCount } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const { triggerOnDemandObservation } = useActions(replayScannerLogic({ id: scannerId }))

    // `pendingId` bridges the gap between clicking Scan and its observation showing up in the fetch below — it
    // stays set until the observation lands (so the spinner never flickers back to the button), and is released
    // on trigger failure. `pendingStartCount` lets us tell a queued scan from a failed one.
    const [pendingId, setPendingId] = useState<string | null>(null)
    const pendingStartCount = useRef(0)

    // A scanner observes each session at most once. Look up each visible recording's observation (id + status):
    // in-progress rows show a spinner, settled rows link to the result. Refetch after each scan and poll while
    // anything visible is still running (or queued), so a row swaps spinner → "View observation" on its own.
    const [observationBySession, setObservationBySession] = useState<Map<string, RowObservation>>(new Map())
    // Drives the table's loading bar on foreground refetches (initial load, post-scan). Background polls
    // reload silently so the table stays interactable instead of blanking on each tick.
    const [refreshingObservations, setRefreshingObservations] = useState(false)
    const visibleIdsKey = sessionRecordings.map((recording) => recording.id).join(',')

    const refetchObservations = useCallback(
        async (background = false) => {
            const ids = visibleIdsKey ? visibleIdsKey.split(',') : []
            if (!currentTeamId || ids.length === 0) {
                return
            }
            if (!background) {
                setRefreshingObservations(true)
            }
            try {
                const response = await visionScannersObservationsList(String(currentTeamId), scannerId, {
                    session_id: visibleIdsKey,
                    limit: ids.length,
                })
                setObservationBySession((prev) => {
                    const next = new Map(prev)
                    for (const observation of response.results ?? []) {
                        next.set(observation.session_id, { id: observation.id, status: observation.status })
                    }
                    return next
                })
            } catch {
                // Best-effort enrichment — on failure we just leave the rows scannable.
            } finally {
                // Only the foreground path touches the flag — a background poll resolving mid-flight must
                // not clear an overlay a concurrent foreground fetch is still showing.
                if (!background) {
                    setRefreshingObservations(false)
                }
            }
        },
        [visibleIdsKey, currentTeamId, scannerId]
    )

    // Initial load + whenever a scan is triggered (which creates a new pending observation to pick up).
    useEffect(() => {
        void refetchObservations()
    }, [refetchObservations, onDemandObservationSuccessCount])

    // Release the bridge if the trigger failed (no new observation was queued) — on success we keep it until the
    // observation appears in the fetch, avoiding a one-frame flicker back to the button.
    useEffect(() => {
        if (triggeringOnDemandObservation || !pendingId) {
            return
        }
        const failed = onDemandObservationSuccessCount <= pendingStartCount.current
        if (failed) {
            setPendingId(null)
        }
    }, [triggeringOnDemandObservation, onDemandObservationSuccessCount, pendingId])

    // Once the queued observation lands, the bridge is no longer needed (its in-progress status drives the spinner).
    useEffect(() => {
        if (pendingId && observationBySession.has(pendingId)) {
            setPendingId(null)
        }
    }, [observationBySession, pendingId])

    const visibleIds = visibleIdsKey ? visibleIdsKey.split(',') : []
    const anyInProgress = visibleIds.some((id) => {
        const observation = observationBySession.get(id)
        return !!observation && IN_PROGRESS_STATUSES.has(observation.status)
    })

    // Poll while a visible row is running or a scan is queued, so the spinner settles into the result button.
    const shouldPoll = anyInProgress || pendingId !== null
    useEffect(() => {
        if (!shouldPoll) {
            return
        }
        const interval = setInterval(() => {
            // Skip polling while the browser tab is backgrounded; it resumes on the next tick when visible again.
            if (document.visibilityState === 'visible') {
                // Background reload — keeps the table interactable instead of blanking it each tick.
                void refetchObservations(true)
            }
        }, 4000)
        return () => clearInterval(interval)
    }, [shouldPoll, refetchObservations])

    const startScan = (sessionId: string): void => {
        if (triggeringOnDemandObservation || pendingId) {
            return
        }
        pendingStartCount.current = onDemandObservationSuccessCount
        setPendingId(sessionId)
        triggerOnDemandObservation(sessionId, true)
    }

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
                const observation = observationBySession.get(recording.id)
                if (observation) {
                    return <ObservationStatusTag status={observation.status} />
                }
                if (pendingId === recording.id) {
                    return (
                        <LemonTag type="warning">
                            <Spinner className="mr-1" /> Scanning
                        </LemonTag>
                    )
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
                const observation = observationBySession.get(recording.id)
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
                        <AccessControlAction
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                fullWidth
                                center
                                size="small"
                                type="secondary"
                                icon={<IconPlay />}
                                disabledReason={
                                    scanning
                                        ? 'Scan in progress…'
                                        : pendingId && pendingId !== recording.id
                                          ? 'Another scan is starting…'
                                          : undefined
                                }
                                onClick={() => startScan(recording.id)}
                                data-attr="vision-run-scan-recording"
                            >
                                Scan recording
                            </LemonButton>
                        </AccessControlAction>
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
    const logicProps: SessionRecordingPlaylistLogicProps = {
        logicKey: `vision-run-${scannerId}`,
        updateSearchParams: false,
    }
    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
            <div>
                <h3 className="text-sm font-medium mb-1">Pick from your recordings</h3>
                <p className="text-muted text-sm m-0">
                    Filter your session recordings and run this scanner against any of them. Each scan produces one
                    observation.
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
