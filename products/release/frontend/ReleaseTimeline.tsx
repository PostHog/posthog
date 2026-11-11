import { useValues } from 'kea'

import { Badge, Dot, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { releaseLogic } from './releaseLogic'
import { ReleaseSpan, STAGE_DOT } from './releaseUtils'

const DAY = 30
const BEFORE = 17
const AFTER = 60
const NAME = 280
const ROW = 48

const SPAN_LOOK: Record<ReleaseSpan['kind'], { top: number; height: number; badge?: 'info' | 'warning' | 'default' }> =
    {
        flag: { top: 23, height: 2 },
        early_access: { top: 38, height: 4, badge: 'warning' },
        experiment: { top: 12, height: 24, badge: 'info' },
        experiment_done: { top: 12, height: 24, badge: 'default' },
    }

export function ReleaseTimeline(): JSX.Element {
    const { filteredRows, dataLoading } = useValues(releaseLogic)
    const today = dayjs().startOf('day')
    const start = today.subtract(BEFORE, 'day')
    const total = BEFORE + AFTER
    const days = Array.from({ length: total }, (_, index) => start.add(index, 'day'))
    const x = (date: string): number => Math.max(0, Math.min(total, dayjs(date).diff(start, 'day'))) * DAY
    const months = days.filter((day, index) => index === 0 || day.date() === 1)

    return (
        <div
            className="overflow-auto rounded-lg border border-border bg-background"
            style={{ maxHeight: 'calc(100vh - 230px)' }}
            data-attr="release-timeline"
        >
            <div className="relative" style={{ width: NAME + total * DAY }}>
                <div className="pointer-events-none absolute inset-y-0" style={{ left: NAME, width: total * DAY }}>
                    {days.map((day, index) =>
                        day.day() === 0 || day.day() === 6 ? (
                            <div
                                key={index}
                                className="absolute inset-y-0 bg-fill-hover"
                                style={{ left: index * DAY, width: DAY }}
                            />
                        ) : null
                    )}
                    <div className="absolute inset-y-0 w-px bg-primary" style={{ left: BEFORE * DAY + DAY / 2 }} />
                </div>
                <div className="sticky top-0 z-20 flex h-14 border-b border-border bg-background">
                    <div
                        className="sticky left-0 z-30 flex shrink-0 items-end border-r border-border bg-background px-3 pb-2 text-xs font-semibold text-muted-foreground"
                        style={{ width: NAME }}
                    >
                        Release
                    </div>
                    <div className="relative" style={{ width: total * DAY }}>
                        {months.map((month) => (
                            <div
                                key={month.format('YYYY-MM-DD')}
                                className="absolute top-1.5 pl-2 text-xs font-semibold"
                                style={{ left: month.diff(start, 'day') * DAY }}
                            >
                                {month.format('MMMM YYYY')}
                            </div>
                        ))}
                        {days.map((day, index) => (
                            <div
                                key={index}
                                className="absolute bottom-1.5 flex justify-center text-xs text-muted-foreground"
                                style={{ left: index * DAY, width: DAY }}
                            >
                                {day.isSame(today, 'day') ? (
                                    <span className="rounded-full bg-primary px-1.5 font-semibold text-primary-foreground">
                                        {day.date()}
                                    </span>
                                ) : (
                                    <span className={day.day() === 1 ? 'font-semibold text-foreground' : ''}>
                                        {day.date()}
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
                {filteredRows.map((row) => (
                    <div
                        key={row.id}
                        className="group flex border-b border-border last:border-b-0"
                        style={{ height: ROW }}
                        data-attr="release-timeline-row"
                    >
                        <LinkPrimitive
                            to={urls.release(row.id)}
                            data-attr="release-timeline-release"
                            className="sticky left-0 z-10 flex shrink-0 items-center gap-2 border-r border-border bg-background px-3 text-foreground group-hover:bg-fill-hover"
                            style={{ width: NAME }}
                        >
                            <Dot variant={STAGE_DOT[row.stage]} />
                            <span className="flex min-w-0 flex-1 flex-col">
                                <Text size="xs" weight="semibold" className="truncate">
                                    {row.name}
                                </Text>
                                <Text size="xs" variant="muted" className="truncate">
                                    {row.status}
                                </Text>
                            </span>
                        </LinkPrimitive>
                        <div className="relative" style={{ width: total * DAY }}>
                            {row.spans.map((span) => {
                                const left = x(span.from)
                                const width = Math.max(x(span.to) + DAY / 2 - left, span.kind === 'flag' ? 0 : DAY)
                                const look = SPAN_LOOK[span.kind]
                                const style = { left, width, top: look.top, height: look.height }
                                return width > 0 ? (
                                    look.badge ? (
                                        <LinkPrimitive
                                            key={span.key}
                                            to={span.href}
                                            title={span.label}
                                            className="absolute flex"
                                            style={style}
                                        >
                                            <Badge
                                                variant={look.badge}
                                                className={cn(
                                                    'h-full w-full justify-start overflow-hidden',
                                                    !span.label && 'p-0'
                                                )}
                                            >
                                                {span.label ? <span className="truncate">{span.label}</span> : null}
                                            </Badge>
                                        </LinkPrimitive>
                                    ) : (
                                        <LinkPrimitive
                                            key={span.key}
                                            to={span.href}
                                            className="absolute rounded-full bg-border"
                                            style={style}
                                        />
                                    )
                                ) : null
                            })}
                            {row.markers.map((marker) => (
                                <div
                                    key={marker.key}
                                    title={`${dayjs(marker.date).format('D MMM')}: ${marker.label} (${marker.flagKey})`}
                                    className="absolute flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-foreground"
                                    style={{ left: x(marker.date) + DAY / 2 - 5, top: 16 }}
                                    data-attr="release-timeline-marker"
                                >
                                    <span className="size-2.5 rotate-45 border-2 border-primary bg-background" />
                                    {marker.label}
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
                {!filteredRows.length && (
                    <div className="sticky left-0 p-8 text-xs text-muted-foreground">
                        {dataLoading ? 'Loading releases…' : 'No release matches these filters.'}
                    </div>
                )}
            </div>
        </div>
    )
}
