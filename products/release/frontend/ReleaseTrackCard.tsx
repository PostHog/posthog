import { CellContext, ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { createContext, useContext, useEffect, useMemo, useState } from 'react'

import { Button, Card, CardDescription, CardHeader, CardTitle, DataTable, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { ReleaseFlagActions, ReleaseVariantWarning, emptyVariantWarning } from './ReleaseFlagActions'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { ReleaseTimelineAxis } from './ReleaseTimelineAxis'
import { ReleaseTrackGrid } from './ReleaseTrackGrid'
import { ReleaseTrackLabel } from './ReleaseTrackLabel'
import { ReleaseTrackLane } from './ReleaseTrackLane'
import { Lane, Scale, Track, buildTrack } from './releaseTracks'
import { CALENDAR_DAYS_AFTER, ReleaseRow, STAGE_COLOR, STAGE_COLOR_VARS, isEnrollingEarlyAccess } from './releaseUtils'
import { useRefreshChangedFlagHistory } from './useRefreshChangedFlagHistory'
import { useRolloutStepsByFlag } from './useRolloutStepsByFlag'
import { useScrollToToday } from './useScrollToToday'
import { useStickyColumnWidth } from './useStickyColumnWidth'

const TRACK_NAME = 264
const NARROW_WIDTH = 560
const TRACK_MIN_DAY = 12
const TRACK_MIN_DAYS = 21
const TRACK_MAX_PAST_DAYS = 90
const TRACK_MAX_FUTURE_DAYS = CALENDAR_DAYS_AFTER
const TRACK_LABEL_ROOM = 120

function trackScale(track: Track, width: number, labelWidth: number): Scale {
    const today = dayjs().startOf('day')
    const dates = [
        ...track.lanes.flatMap((lane) =>
            lane.kind === 'flag'
                ? lane.steps.length
                    ? [lane.steps[0].from, lane.steps[lane.steps.length - 1].from]
                    : [lane.span.from]
                : lane.kind === 'broadcast'
                  ? lane.events.map((event) => event.date)
                  : 'span' in lane && lane.span
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
    const estimate = Math.max(TRACK_MIN_DAY, Math.floor((width - labelWidth) / (base + 8)))
    const days = Math.max(base + Math.max(4, Math.ceil(TRACK_LABEL_ROOM / estimate)), TRACK_MIN_DAYS)
    return { start, days, day: Math.max(TRACK_MIN_DAY, Math.floor((width - labelWidth) / days)) }
}

function FlagHistoryLoader({ flagId, onLoad }: { flagId: number; onLoad: (flagIds: number[]) => void }): null {
    useEffect(() => {
        onLoad([flagId])
    }, [flagId, onLoad])
    return null
}

interface TrackCardState {
    row: ReleaseRow
    labelWidth: number
    stickyOffset: number
    width: number
    stacked: boolean
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
    const { row, labelWidth } = useTrackCard()
    return (
        <ReleaseTrackLabel
            lane={lane.original}
            style={{ width: labelWidth - 24 }}
            detailed
            actions={
                lane.original.kind === 'flag' ? <ReleaseFlagActions row={row} flag={lane.original.flag} /> : undefined
            }
        />
    )
}

function TrackLaneCell({ row: lane }: CellContext<Lane, unknown>): JSX.Element {
    const { row, scale, color, lanesByKey, loadFlagActivity, stacked, width, stickyOffset } = useTrackCard()
    return (
        <div className="relative" style={{ width: scale.days * scale.day }}>
            <ReleaseTrackGrid scale={scale} />
            {stacked && (
                <ReleaseTrackLabel
                    lane={lane.original}
                    inline
                    className="sticky left-0 z-10 w-fit rounded-br-md bg-card py-0.5 pr-2 pl-3 mt-1.5"
                    style={{ maxWidth: width - 1 }}
                    actions={
                        lane.original.kind === 'flag' ? (
                            <ReleaseFlagActions row={row} flag={lane.original.flag} />
                        ) : undefined
                    }
                />
            )}
            <ReleaseTrackLane
                lane={lanesByKey.get(lane.original.key) ?? lane.original}
                color={color}
                scale={scale}
                detailed={!stacked}
                flush
                stickyOffset={stickyOffset}
            />
            {lane.original.kind === 'flag' && (
                <FlagHistoryLoader flagId={lane.original.flag.id} onLoad={loadFlagActivity} />
            )}
        </div>
    )
}

function TrackAxisHeader(): JSX.Element {
    const { scale, stickyOffset } = useTrackCard()
    return <ReleaseTimelineAxis scale={scale} stickyOffset={stickyOffset} />
}

function trackColumns(labelWidth: number, stacked: boolean): ColumnDef<Lane>[] {
    const timeline: ColumnDef<Lane> = {
        id: 'timeline',
        header: TrackAxisHeader,
        enableSorting: false,
        cell: TrackLaneCell,
    }
    if (stacked) {
        return [timeline]
    }
    return [
        {
            id: 'lane',
            header: 'Track',
            size: labelWidth,
            enableSorting: false,
            meta: { sticky: 'left' },
            cell: TrackLabelCell,
        },
        timeline,
    ]
}

export function ReleaseTrackCard({ row }: { row: ReleaseRow }): JSX.Element | null {
    const { failedFlagIds } = useValues(releaseCalendarLogic)
    const { loadFlagActivity } = useActions(releaseCalendarLogic)
    const { ref, width = 0 } = useResizeObserver<HTMLDivElement>()
    const [container, setContainer] = useState<HTMLDivElement | null>(null)
    useRefreshChangedFlagHistory(row.flags)

    const stepsByFlag = useRolloutStepsByFlag(TRACK_MAX_FUTURE_DAYS)
    const { relatedByRelease } = useValues(releaseRelatedLogic)
    const related = relatedByRelease[row.id]
    const track = useMemo(() => buildTrack(row, stepsByFlag, related), [row, stepsByFlag, related])

    const rows = useMemo(() => buildTrack(row, new Map(), related).lanes, [row, related])
    const lanesByKey = useMemo(() => new Map(track.lanes.map((lane) => [lane.key, lane])), [track])
    const stacked = width > 0 && width < NARROW_WIDTH
    const labelWidth = stacked ? 0 : TRACK_NAME
    const columns = useMemo(() => trackColumns(labelWidth, stacked), [labelWidth, stacked])
    const scale = useMemo(() => trackScale(track, width, labelWidth), [track, width, labelWidth])
    const measuredOffset = useStickyColumnWidth(stacked ? null : container, labelWidth)
    const stickyOffset = stacked ? 0 : measuredOffset
    useScrollToToday(container, scale, stickyOffset, width > 0 && track.lanes.length > 0)
    const color = STAGE_COLOR[row.stage]
    const warnings = row.audiences.flatMap((audience) => {
        const warning = emptyVariantWarning(row, audience)
        return warning ? [{ audience, warning }] : []
    })
    const openEarlyAccess = row.earlyAccess.find(isEnrollingEarlyAccess)
    const failedFlags = row.flags.filter((flag) => failedFlagIds.includes(flag.id))

    const state = useMemo(
        () => ({ row, labelWidth, stickyOffset, width, stacked, scale, color, lanesByKey, loadFlagActivity }),
        [row, labelWidth, stickyOffset, width, stacked, scale, color, lanesByKey, loadFlagActivity]
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
                ref={(node) => {
                    ref(node)
                    setContainer(node)
                }}
                className="overflow-hidden border-t border-border [--quill-table-sticky-bg:var(--card)] [&_td]:py-0 [&_td]:align-top [&_td+td]:p-0 [&_th+th]:p-0"
            >
                {width > 0 && (
                    <TrackCardContext.Provider value={state}>
                        <DataTable
                            columns={columns}
                            data={rows}
                            size="sm"
                            getRowId={(lane) => lane.key}
                            rowClassName={() => 'group/track'}
                        />
                    </TrackCardContext.Provider>
                )}
            </div>
        </Card>
    )
}
