import { CellContext, ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { createContext, useContext, useEffect, useMemo } from 'react'

import { Button, Card, CardDescription, CardHeader, CardTitle, DataTable, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { ReleaseFlagActions, ReleaseVariantWarning, emptyVariantWarning } from './ReleaseFlagActions'
import { releaseLogic } from './releaseLogic'
import { RolloutStep, rolloutSteps } from './releaseRollout'
import { ReleaseTimelineAxis } from './ReleaseTimelineAxis'
import { ReleaseTrackGrid } from './ReleaseTrackGrid'
import { ReleaseTrackLabel } from './ReleaseTrackLabel'
import { ReleaseTrackLane } from './ReleaseTrackLane'
import { Lane, Scale, Track, buildTrack } from './releaseTracks'
import { ReleaseRow, STAGE_COLOR, STAGE_COLOR_VARS, isEnrollingEarlyAccess } from './releaseUtils'
import { useRefreshChangedFlagHistory } from './useRefreshChangedFlagHistory'

const TRACK_NAME = 264
const TRACK_MIN_DAY = 12
const TRACK_MIN_DAYS = 21
const TRACK_MAX_PAST_DAYS = 90
const TRACK_MAX_FUTURE_DAYS = 90
const TRACK_PAGE_SIZE = 20
const TRACK_LABEL_ROOM = 120

function trackScale(track: Track, width: number): Scale {
    const today = dayjs().startOf('day')
    const dates = [
        ...track.lanes.flatMap((lane) =>
            lane.kind === 'flag'
                ? lane.steps.map((step) => step.from)
                : lane.kind === 'broadcast'
                  ? lane.events.map((event) => event.date)
                  : lane.span
                    ? [lane.span.from, lane.span.to]
                    : []
        ),
        ...track.row.events.filter((event) => event.upcoming).map((event) => event.date),
    ].map((date) => dayjs(date).startOf('day'))
    const earliest = dates.reduce((min, date) => (date.isBefore(min) ? date : min), today)
    const ceiling = today.add(TRACK_MAX_FUTURE_DAYS, 'day')
    const latest = dates.reduce((max, date) => (date.isAfter(max) ? date : max), today)
    const floor = today.subtract(TRACK_MAX_PAST_DAYS, 'day')
    const start = (earliest.isBefore(floor) ? floor : earliest).subtract(2, 'day')
    const base = (latest.isAfter(ceiling) ? ceiling : latest).diff(start, 'day') + 1
    const estimate = Math.max(TRACK_MIN_DAY, Math.floor((width - TRACK_NAME) / (base + 8)))
    const days = Math.max(base + Math.max(4, Math.ceil(TRACK_LABEL_ROOM / estimate)), TRACK_MIN_DAYS)
    return { start, days, day: Math.max(TRACK_MIN_DAY, Math.floor((width - TRACK_NAME) / days)) }
}

function FlagHistoryLoader({ flagId, onLoad }: { flagId: number; onLoad: (flagIds: number[]) => void }): null {
    useEffect(() => {
        onLoad([flagId])
    }, [flagId, onLoad])
    return null
}

interface TrackCardState {
    row: ReleaseRow
    scale: Scale
    color: string
    lanesByKey: Map<string, Lane>
    loadFlagActivity: (flagIds: number[]) => void
}

const TrackCardContext = createContext<TrackCardState | null>(null)

function useTrackCard(): TrackCardState {
    const state = useContext(TrackCardContext)
    if (!state) {
        throw new Error('Track card cells render inside ReleaseTrackCard')
    }
    return state
}

function TrackLabelCell({ row: lane }: CellContext<Lane, unknown>): JSX.Element {
    const { row } = useTrackCard()
    return (
        <ReleaseTrackLabel
            lane={lane.original}
            className="w-60"
            detailed
            actions={
                lane.original.kind === 'flag' ? <ReleaseFlagActions row={row} flag={lane.original.flag} /> : undefined
            }
        />
    )
}

function TrackLaneCell({ row: lane }: CellContext<Lane, unknown>): JSX.Element {
    const { scale, color, lanesByKey, loadFlagActivity } = useTrackCard()
    return (
        <div className="relative" style={{ width: scale.days * scale.day }}>
            <ReleaseTrackGrid scale={scale} />
            <ReleaseTrackLane
                lane={lanesByKey.get(lane.original.key) ?? lane.original}
                color={color}
                scale={scale}
                detailed
            />
            {lane.original.kind === 'flag' && (
                <FlagHistoryLoader flagId={lane.original.flag.id} onLoad={loadFlagActivity} />
            )}
        </div>
    )
}

function TrackAxisHeader(): JSX.Element {
    const { scale } = useTrackCard()
    return <ReleaseTimelineAxis scale={scale} />
}

const COLUMNS: ColumnDef<Lane>[] = [
    {
        id: 'lane',
        header: 'Track',
        size: TRACK_NAME,
        enableSorting: false,
        meta: { sticky: 'left' },
        cell: TrackLabelCell,
    },
    { id: 'timeline', header: TrackAxisHeader, enableSorting: false, cell: TrackLaneCell },
]

export function ReleaseTrackCard({ row }: { row: ReleaseRow }): JSX.Element | null {
    const { flags, scheduledChanges } = useValues(releaseLogic)
    const { flagActivity, failedFlagIds } = useValues(releaseCalendarLogic)
    const { loadFlagActivity } = useActions(releaseCalendarLogic)
    const { ref, width = 0 } = useResizeObserver<HTMLDivElement>()
    useRefreshChangedFlagHistory(row.flags)

    const track = useMemo(() => {
        const today = dayjs()
        const horizon = today.add(TRACK_MAX_PAST_DAYS, 'day')
        const stepsByFlag = new Map<number, RolloutStep[]>()
        for (const flag of flags) {
            if (flagActivity[flag.id]) {
                stepsByFlag.set(flag.id, rolloutSteps(flag, flagActivity[flag.id], scheduledChanges, today, horizon))
            }
        }
        return buildTrack(row, stepsByFlag)
    }, [row, flags, flagActivity, scheduledChanges])

    const rows = useMemo(() => buildTrack(row, new Map()).lanes, [row])
    const lanesByKey = useMemo(() => new Map(track.lanes.map((lane) => [lane.key, lane])), [track])
    const scale = useMemo(() => trackScale(track, width), [track, width])
    const color = STAGE_COLOR[row.stage]
    const warnings = row.audiences.flatMap((audience) => {
        const warning = emptyVariantWarning(row, audience)
        return warning ? [{ audience, warning }] : []
    })
    const openEarlyAccess = row.earlyAccess.find(isEnrollingEarlyAccess)
    const failedFlags = row.flags.filter((flag) => failedFlagIds.includes(flag.id))

    const state = useMemo(
        () => ({ row, scale, color, lanesByKey, loadFlagActivity }),
        [row, scale, color, lanesByKey, loadFlagActivity]
    )

    if (!track.lanes.length) {
        return null
    }

    return (
        <Card flush data-attr="release-track-card" className={STAGE_COLOR_VARS}>
            <CardHeader>
                <CardTitle>Calendar</CardTitle>
                <CardDescription>
                    Who gets each part of this release, day by day. Change who gets a flag in its release conditions.
                </CardDescription>
            </CardHeader>
            {(warnings.length > 0 || openEarlyAccess || failedFlags.length > 0) && (
                <div className="flex flex-col gap-2 px-4 pb-3">
                    {failedFlags.length > 0 && (
                        <div className="flex items-center gap-2">
                            <Text size="xs" variant="muted">
                                {failedFlags.length === 1
                                    ? `Couldn't load the rollout history of ${failedFlags[0].key}.`
                                    : `Couldn't load the rollout history of ${failedFlags.length} flags.`}
                            </Text>
                            <Button
                                size="xs"
                                variant="outline"
                                onClick={() => loadFlagActivity(failedFlags.map((flag) => flag.id))}
                                data-attr="release-track-history-retry"
                            >
                                Try again
                            </Button>
                        </div>
                    )}
                    {warnings.map(({ audience, warning }) => (
                        <ReleaseVariantWarning key={audience.flag.id} flag={audience.flag} warning={warning} />
                    ))}
                    {openEarlyAccess && (
                        <Text size="xs" variant="muted">
                            {`Users can also opt in through ${openEarlyAccess.name}, now in ${openEarlyAccess.stage}.`}
                        </Text>
                    )}
                </div>
            )}
            <div
                ref={ref}
                className="overflow-hidden border-t border-border [--quill-table-sticky-bg:var(--card)] [&_td]:py-0 [&_td]:align-top [&_td+td]:p-0 [&_th+th]:p-0"
            >
                {width > 0 && (
                    <TrackCardContext.Provider value={state}>
                        <DataTable
                            columns={COLUMNS}
                            data={rows}
                            size="sm"
                            getRowId={(lane) => lane.key}
                            pageSize={track.lanes.length > TRACK_PAGE_SIZE ? TRACK_PAGE_SIZE : undefined}
                            rowClassName={() => 'group/track'}
                        />
                    </TrackCardContext.Provider>
                )}
            </div>
        </Card>
    )
}
