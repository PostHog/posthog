import { useState } from 'react'

import { IconCalendar, IconFlag } from '@posthog/icons'
import { Card, CardContent, CardHeader, CardTitle, Text, cn } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { ReleaseShowMore } from './ReleaseShowMore'
import { ReleaseEvent, ReleaseRow } from './releaseUtils'

const HISTORY_LIMIT = 4

const KIND_TYPE: Partial<Record<ReleaseEvent['kind'], string>> = {
    flag: 'feature_flag',
    experiment: 'experiment',
    early_access: 'early_access_feature',
    broadcast: 'broadcasts',
}

function EventIcon({ kind }: { kind: ReleaseEvent['kind'] }): JSX.Element {
    const type = KIND_TYPE[kind]
    return (
        <span className="flex size-6 shrink-0 items-center justify-center rounded-md border border-border bg-background [&_svg]:size-3.5">
            {type ? iconForType(type as FileSystemIconType) : kind === 'schedule' ? <IconCalendar /> : <IconFlag />}
        </span>
    )
}

function EventRow({ event }: { event: ReleaseEvent }): JSX.Element {
    const title = (
        <Text size="xs" weight="medium" className="truncate">
            {event.title}
        </Text>
    )
    return (
        <li className="relative flex items-start gap-3" data-attr="release-event">
            <EventIcon kind={event.kind} />
            <div className="flex min-w-0 flex-1 flex-col pt-0.5">
                {event.href ? (
                    <LinkPrimitive to={event.href} className="min-w-0 truncate text-foreground hover:underline">
                        {title}
                    </LinkPrimitive>
                ) : (
                    title
                )}
                {event.detail && (
                    <Text size="xs" variant="muted" className="truncate">
                        {event.detail}
                    </Text>
                )}
            </div>
            <Text size="xs" variant="muted" render={<span />} className="shrink-0 pt-0.5">
                <TZLabel time={event.date} formatDate="D MMM YYYY" formatTime="" />
            </Text>
        </li>
    )
}

function EventList({ events, dashed }: { events: ReleaseEvent[]; dashed?: boolean }): JSX.Element {
    return (
        <ol className="relative m-0 flex list-none flex-col gap-3 p-0">
            <span
                className={cn('absolute bottom-3 left-3 top-3 border-l border-border', dashed && 'border-dashed')}
                aria-hidden
            />
            {events.map((event) => (
                <EventRow key={event.key} event={event} />
            ))}
        </ol>
    )
}

export function ReleaseHistory({ row }: { row: ReleaseRow }): JSX.Element {
    const [visible, setVisible] = useState(HISTORY_LIMIT)
    const [upcomingVisible, setUpcomingVisible] = useState(HISTORY_LIMIT)
    const upcoming = row.events.filter((event) => event.upcoming).sort((a, b) => a.date.localeCompare(b.date))
    const past = row.events.filter((event) => !event.upcoming).sort((a, b) => b.date.localeCompare(a.date))
    const shownPast = past.slice(0, visible)

    return (
        <Card data-attr="release-timeline-card">
            <CardHeader>
                <CardTitle>Timeline</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                    <Text size="xxs" weight="semibold" variant="muted" className="uppercase tracking-wide">
                        Coming up
                    </Text>
                    {upcoming.length ? (
                        <>
                            <EventList events={upcoming.slice(0, upcomingVisible)} dashed />
                            <ReleaseShowMore
                                total={upcoming.length}
                                visible={upcomingVisible}
                                limit={HISTORY_LIMIT}
                                onChange={setUpcomingVisible}
                                dataAttr="release-timeline-upcoming"
                            />
                        </>
                    ) : (
                        <Text size="xs" variant="muted">
                            {row.flags.length
                                ? 'Nothing is scheduled. Use Schedule a change to roll out on a date.'
                                : 'Nothing is scheduled.'}
                        </Text>
                    )}
                </div>
                <div className="flex flex-col gap-2">
                    <Text size="xxs" weight="semibold" variant="muted" className="uppercase tracking-wide">
                        So far
                    </Text>
                    <EventList events={shownPast} />
                    <ReleaseShowMore
                        total={past.length}
                        visible={visible}
                        limit={HISTORY_LIMIT}
                        onChange={setVisible}
                        dataAttr="release-timeline-past"
                    />
                </div>
            </CardContent>
        </Card>
    )
}
