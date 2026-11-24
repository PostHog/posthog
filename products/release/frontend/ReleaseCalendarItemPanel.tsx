import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import {
    Badge,
    Button,
    Drawer,
    DrawerBody,
    DrawerContent,
    DrawerDescription,
    DrawerFooter,
    DrawerHeader,
    DrawerTitle,
    Text,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { KIND_ICON, laneCardFacts } from './ReleaseLaneCard'
import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { Lane, buildTrack, sendLabel, statusLabel } from './releaseTracks'
import { CALENDAR_DAYS_AFTER, ReleaseRow } from './releaseUtils'
import { useRolloutStepsByFlag } from './useRolloutStepsByFlag'

const KIND_LABEL: Record<Lane['kind'], string> = {
    flag: 'Feature flag',
    experiment: 'Experiment',
    early_access: 'Early access feature',
    broadcast: 'Broadcast',
    survey: 'Survey',
}

function date(value: string): string {
    return dayjs(value).format('D MMM YYYY')
}

function History({ lane }: { lane: Lane }): JSX.Element | null {
    const entries =
        lane.kind === 'flag'
            ? [...lane.steps].reverse().map((step) => ({
                  key: `${step.from}-${step.label}`,
                  label: step.label === 'Everyone' ? '100%' : step.label,
                  detail: step.upcoming ? `Planned for ${date(step.from)}` : `From ${date(step.from)}`,
              }))
            : lane.kind === 'broadcast'
              ? [...lane.events].reverse().map((event) => ({
                    key: event.key,
                    label: sendLabel(event),
                    detail: date(event.date),
                }))
              : []
    if (!entries.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" weight="medium">
                {lane.kind === 'flag' ? 'Rollout history' : 'Sends'}
            </Text>
            <div className="grid grid-cols-[5rem_minmax(0,1fr)] gap-x-2 gap-y-1.5">
                {entries.map((entry) => (
                    <div key={entry.key} className="contents">
                        <Text size="xs" className="truncate tabular-nums">
                            {entry.label}
                        </Text>
                        <Text size="xs" variant="muted" className="truncate">
                            {entry.detail}
                        </Text>
                    </div>
                ))}
            </div>
        </div>
    )
}

function ItemDetails({ row, lane }: { row: ReleaseRow; lane: Lane }): JSX.Element {
    const span = 'span' in lane && lane.span && !(lane.kind === 'flag' && lane.steps.length) ? lane.span : undefined
    const facts = laneCardFacts({ lane, span }).filter(([label]) => label !== 'Status')
    return (
        <>
            <DrawerHeader>
                <DrawerTitle className="flex min-w-0 items-center gap-2">
                    <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-4">
                        {iconForType(KIND_ICON[lane.kind] as never)}
                    </span>
                    <span className="truncate">{lane.title}</span>
                </DrawerTitle>
                <DrawerDescription>
                    {KIND_LABEL[lane.kind]} in{' '}
                    <LinkPrimitive to={urls.release(row.id)} className="text-foreground hover:underline">
                        {row.name}
                    </LinkPrimitive>
                </DrawerDescription>
            </DrawerHeader>
            <DrawerBody>
                <div className="flex flex-col gap-4">
                    <div className="flex items-center gap-2">
                        <Text size="xs" variant="muted">
                            Status
                        </Text>
                        <Badge variant={lane.live ? 'success' : 'default'}>{statusLabel(lane.status)}</Badge>
                    </div>
                    {facts.length > 0 && (
                        <div className="grid grid-cols-[5rem_minmax(0,1fr)] gap-x-2 gap-y-1.5">
                            {facts.map(([label, value]) => (
                                <div key={label} className="contents">
                                    <Text size="xs" variant="muted" className="truncate">
                                        {label}
                                    </Text>
                                    <Text size="xs" className="truncate" title={value}>
                                        {value}
                                    </Text>
                                </div>
                            ))}
                        </div>
                    )}
                    <History lane={lane} />
                </div>
            </DrawerBody>
            <DrawerFooter>
                <Button
                    variant="primary"
                    nativeButton={false}
                    render={<LinkPrimitive to={lane.href} />}
                    data-attr="release-calendar-item-panel-open"
                >
                    Open {KIND_LABEL[lane.kind].toLowerCase()}
                </Button>
            </DrawerFooter>
        </>
    )
}

export function ReleaseCalendarItemPanel(): JSX.Element {
    const { openItem } = useValues(releaseCalendarLogic)
    const { closeCalendarItem } = useActions(releaseCalendarLogic)
    const { rows } = useValues(releaseLogic)
    const { relatedByRelease } = useValues(releaseRelatedLogic)
    const stepsByFlag = useRolloutStepsByFlag(CALENDAR_DAYS_AFTER)
    const shown = useRef<{ row: ReleaseRow; lane: Lane } | null>(null)

    useEffect(() => () => closeCalendarItem(), [closeCalendarItem])

    const current = useMemo(() => {
        const row = openItem ? rows.find((item) => item.id === openItem.releaseId) : undefined
        const lane = row
            ? buildTrack(row, stepsByFlag, relatedByRelease[row.id]).lanes.find(
                  (item) => item.key === openItem?.laneKey
              )
            : undefined
        return row && lane ? { row, lane } : null
    }, [openItem, rows, stepsByFlag, relatedByRelease])

    if (current) {
        shown.current = current
    }

    return (
        <Drawer open={!!current} onOpenChange={(open: boolean) => !open && closeCalendarItem()} swipeDirection="right">
            <DrawerContent data-attr="release-calendar-item-panel">
                {shown.current && <ItemDetails row={shown.current.row} lane={shown.current.lane} />}
            </DrawerContent>
        </Drawer>
    )
}
