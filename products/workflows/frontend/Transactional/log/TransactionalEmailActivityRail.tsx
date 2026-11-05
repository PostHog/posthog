import clsx from 'clsx'
import { ReactNode } from 'react'

import { IconLetter } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ActivityRow, describeActivityEvent, isCustomEvent, relativeToSend } from './emailActivity'
import { ActivityGroup, gapBetween, groupDuration } from './emailActivityGroups'
import { EMAIL_STATUS_LABEL, EMAIL_STATUS_TAG } from './emailLogStatus'

type Marker = 'event' | 'outcome' | 'email'

function RailLine({
    inSession,
    position,
}: {
    inSession: boolean
    position: 'first' | 'middle' | 'last' | 'only'
}): JSX.Element | null {
    if (position === 'only') {
        return null
    }
    return (
        <span
            className={clsx(
                'absolute left-1/2 -translate-x-1/2',
                position === 'first' ? 'top-1/2' : 'top-0',
                position === 'last' ? 'bottom-1/2' : 'bottom-0',
                'bg-muted opacity-40',
                inSession ? 'w-0.5' : 'w-px'
            )}
        />
    )
}

function RailRow({
    time,
    inSession = false,
    position,
    marker,
    children,
}: {
    time?: ReactNode
    inSession?: boolean
    position: 'first' | 'middle' | 'last' | 'only'
    marker?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <li className="grid grid-cols-[3.5rem_1.25rem_minmax(0,1fr)] gap-x-2 min-h-8">
            <span className="flex items-center text-xs text-secondary tabular-nums whitespace-nowrap">{time}</span>
            <span className="relative flex items-center justify-center">
                <RailLine inSession={inSession} position={position} />
                {marker}
            </span>
            <div className="flex items-center gap-2 min-w-0">{children}</div>
        </li>
    )
}

function Dot({ marker }: { marker: Marker }): JSX.Element {
    return (
        <span
            className={clsx(
                'relative size-2 rounded-full border',
                marker === 'event' && 'bg-surface-primary border-muted',
                marker === 'outcome' && 'bg-warning border-warning',
                marker === 'email' && 'bg-surface-primary border-accent'
            )}
        />
    )
}

function Time({ at, sentAt }: { at: string; sentAt: string }): JSX.Element {
    return (
        <Tooltip title={relativeToSend(at, sentAt)}>
            <span>{dayjs(at).format('HH:mm:ss')}</span>
        </Tooltip>
    )
}

function RowContent({ row }: { row: ActivityRow }): JSX.Element {
    if (row.kind === 'otherEmail') {
        return (
            <>
                <span className="text-sm truncate">
                    Got{' '}
                    <Link
                        to={urls.transactionalEmailLogEntry(row.entry.message_id)}
                        data-attr="transactional-email-activity-other-email"
                    >
                        {row.entry.template_name || 'a deleted email'}
                    </Link>
                </span>
                <LemonTag size="small" type={EMAIL_STATUS_TAG[row.entry.status]} className="shrink-0">
                    {EMAIL_STATUS_LABEL[row.entry.status]}
                </LemonTag>
            </>
        )
    }
    const description = describeActivityEvent(row.event)
    return (
        <span className={clsx('text-sm truncate', isCustomEvent(row.event) && 'font-semibold')} title={description}>
            {description}
            {row.count > 1 && <span className="font-normal text-secondary"> ×{row.count}</span>}
        </span>
    )
}

function SessionLabel({ group }: { group: ActivityGroup }): JSX.Element {
    return (
        <>
            <span className="text-xs font-semibold uppercase tracking-wide text-secondary">Session</span>
            <span className="text-xs text-secondary whitespace-nowrap">
                {groupDuration(group)} · {pluralize(group.eventCount, 'event')}
            </span>
            <span className="flex-1" />
            <ViewRecordingButton
                sessionId={group.sessionId as string}
                timestamp={group.startAt}
                checkRecordingExists
                openPlayerIn={RecordingPlayerType.Modal}
                size="xsmall"
                type="secondary"
                label="Watch"
                data-attr="transactional-email-activity-recording"
            />
        </>
    )
}

type RailItem =
    | { key: string; kind: 'earlier' }
    | { key: string; kind: 'date'; label: string; inSession: boolean }
    | { key: string; kind: 'session'; group: ActivityGroup }
    | { key: string; kind: 'row'; row: ActivityRow; inSession: boolean }
    | { key: string; kind: 'gap'; text: string; highlighted: boolean }
    | { key: string; kind: 'send' }
    | { key: string; kind: 'note'; text: string }

function dayLabel(at: string): string {
    return dayjs(at).format('MMM D')
}

/** Flattens the groups into one list, with a date row wherever the list crosses into another day. */
function buildRailItems(
    before: ActivityGroup[],
    after: ActivityGroup[],
    sentAt: string,
    comeback: string | null,
    emptyAfter: string | null,
    hasEarlier: boolean
): RailItem[] {
    const items: RailItem[] = hasEarlier ? [{ key: 'earlier', kind: 'earlier' }] : []
    let day = dayLabel(before[0]?.startAt ?? sentAt)
    if (day !== dayLabel(sentAt)) {
        items.push({ key: `date-${day}`, kind: 'date', label: day, inSession: false })
    }
    const addDate = (at: string, inSession: boolean): void => {
        if (dayLabel(at) !== day) {
            day = dayLabel(at)
            items.push({ key: `date-${day}`, kind: 'date', label: day, inSession })
        }
    }
    const addGroups = (groups: ActivityGroup[], firstGapFrom: string | null): void => {
        groups.forEach((group, index) => {
            const previousEnd = index > 0 ? groups[index - 1].endAt : firstGapFrom
            const gap = previousEnd ? gapBetween(previousEnd, group.startAt) : null
            if (gap && dayLabel(group.startAt) === day) {
                items.push({ key: `gap-${group.key}`, kind: 'gap', text: gap, highlighted: false })
            }
            addDate(group.startAt, false)
            if (group.sessionId) {
                items.push({ key: `session-${group.key}`, kind: 'session', group })
            }
            for (const row of group.rows) {
                addDate(row.at, !!group.sessionId)
                items.push({ key: row.key, kind: 'row', row, inSession: !!group.sessionId })
            }
        })
    }
    addGroups(before, null)
    addDate(sentAt, false)
    items.push({ key: 'send', kind: 'send' })
    if (comeback) {
        items.push({ key: 'comeback', kind: 'gap', text: comeback, highlighted: true })
    }
    addGroups(after, comeback ? null : sentAt)
    if (emptyAfter) {
        items.push({ key: 'empty', kind: 'note', text: emptyAfter })
    }
    return items
}

export function TransactionalEmailActivityRail({
    before,
    after,
    sentAt,
    failed,
    sendLabel,
    sendDetail,
    comeback,
    emptyAfter,
    hiddenBefore,
    onShowEarlier,
}: {
    before: ActivityGroup[]
    after: ActivityGroup[]
    sentAt: string
    failed: boolean
    sendLabel: string
    sendDetail: string | null
    comeback: string | null
    emptyAfter: string | null
    hiddenBefore: number
    onShowEarlier: () => void
}): JSX.Element {
    const items = buildRailItems(before, after, sentAt, comeback, emptyAfter, hiddenBefore > 0)
    return (
        <ol className="flex flex-col m-0 p-0 list-none" data-attr="transactional-email-activity">
            {items.map((item, index) => {
                const position =
                    items.length === 1 ? 'only' : index === 0 ? 'first' : index === items.length - 1 ? 'last' : 'middle'
                if (item.kind === 'earlier') {
                    return (
                        <RailRow key={item.key} position={position}>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                className="-ml-1.5"
                                onClick={onShowEarlier}
                                data-attr="transactional-email-activity-show-earlier"
                            >
                                Show {pluralize(hiddenBefore, 'earlier event')}
                            </LemonButton>
                        </RailRow>
                    )
                }
                if (item.kind === 'date') {
                    return (
                        <RailRow key={item.key} position={position} inSession={item.inSession}>
                            <span className="text-xs font-semibold text-secondary">{item.label}</span>
                        </RailRow>
                    )
                }
                if (item.kind === 'session') {
                    return (
                        <RailRow key={item.key} position={position} inSession>
                            <SessionLabel group={item.group} />
                        </RailRow>
                    )
                }
                if (item.kind === 'gap') {
                    return (
                        <RailRow key={item.key} position={position}>
                            <span
                                className={clsx(
                                    'text-xs truncate',
                                    item.highlighted ? 'font-semibold text-success' : 'text-secondary'
                                )}
                            >
                                {item.text}
                            </span>
                        </RailRow>
                    )
                }
                if (item.kind === 'note') {
                    return (
                        <RailRow key={item.key} position={position}>
                            <span className="text-sm text-secondary">{item.text}</span>
                        </RailRow>
                    )
                }
                if (item.kind === 'send') {
                    return (
                        <RailRow
                            key={item.key}
                            position={position}
                            time={dayjs(sentAt).format('HH:mm:ss')}
                            marker={
                                <span
                                    className={clsx(
                                        'relative flex items-center justify-center size-5 rounded-full',
                                        failed ? 'bg-danger text-white' : 'bg-accent text-primary-inverse'
                                    )}
                                >
                                    <IconLetter className="size-3" />
                                </span>
                            }
                        >
                            <div
                                className={clsx(
                                    'flex flex-1 flex-wrap items-center gap-x-2 min-w-0 rounded border px-2 py-1 my-1 text-sm font-semibold',
                                    failed
                                        ? 'border-danger bg-danger-highlight text-danger'
                                        : 'border-accent bg-accent-highlight-secondary text-accent'
                                )}
                            >
                                {sendLabel}
                                {sendDetail && (
                                    <span className="text-xs font-normal text-secondary truncate">{sendDetail}</span>
                                )}
                            </div>
                        </RailRow>
                    )
                }
                const { row, inSession } = item
                const marker: Marker =
                    row.kind === 'otherEmail' ? 'email' : isCustomEvent(row.event) ? 'outcome' : 'event'
                return (
                    <RailRow
                        key={item.key}
                        position={position}
                        inSession={inSession}
                        time={<Time at={row.at} sentAt={sentAt} />}
                        marker={<Dot marker={marker} />}
                    >
                        <RowContent row={row} />
                    </RailRow>
                )
            })}
        </ol>
    )
}
