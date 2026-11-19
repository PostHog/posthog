// PROTOTYPE (throwaway): overview B, performance. Sent, delivered, opened and clicked per messaging type for
// the last 30 days, with a channel switch, send health as risks, and one outcome next to engagement.
import { useState } from 'react'

import {
    Heading,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { OverviewMetric } from './OverviewMetric'
import { CHANNEL_LABEL, Channel, EntryKind, SERIES, formatCount, percent, sum } from './prototypeData'

const KIND_ROWS: { kind: EntryKind; label: string }[] = [
    { kind: 'broadcast', label: 'Broadcasts' },
    { kind: 'workflow', label: 'Workflows' },
    { kind: 'transactional', label: 'Transactional' },
]

const TOP_BROADCASTS = [
    { name: 'October product update', sent: 12480, opened: 0.47, clicked: 0.08 },
    { name: 'Webinar invite: funnels in practice', sent: 3210, opened: 0.38, clicked: 0.11 },
    { name: 'Mobile app release note', sent: 7400, opened: 0.12, clicked: 0.04 },
]

function addSeries(rows: number[][]): number[] {
    return Array.from({ length: 30 }, (_, i) => sum(rows.map((row) => row[i] ?? 0)))
}

export function OverviewPerformance(): JSX.Element {
    const [channel, setChannel] = useState<Channel>('email')
    const rows = SERIES.filter((s) => s.channel === channel)
    const sentSeries = addSeries(rows.map((s) => s.sent))
    const sent = sum(sentSeries)
    const weighted = (pick: (s: (typeof rows)[number]) => number): number =>
        sent ? sum(rows.map((s) => sum(s.sent) * pick(s))) / sent : 0
    const delivered = weighted((s) => s.deliveredRate)
    const opened = weighted((s) => s.openRate)
    const clicked = weighted((s) => s.clickRate)

    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Heading size="sm">Last 30 days</Heading>
                <ToggleGroup
                    variant="outline"
                    aria-label="Channel"
                    value={[channel]}
                    onValueChange={(next: string[]) => next[0] && setChannel(next[0] as Channel)}
                >
                    {(['email', 'sms', 'push'] as Channel[]).map((c) => (
                        <ToggleGroupItem key={c} value={c}>
                            {CHANNEL_LABEL[c]}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
            <div className="grid grid-cols-2 gap-3 @min-[48rem]:grid-cols-4">
                <OverviewMetric title="Messages sent" value={sent} data={sentSeries} change={12} format={formatCount} />
                <OverviewMetric
                    title="Delivered"
                    value={delivered * 100}
                    change={-0.4}
                    format={(v) => `${v.toFixed(1)}%`}
                    subtitle="of messages sent"
                />
                {channel !== 'sms' ? (
                    <OverviewMetric
                        title="Opened"
                        value={opened * 100}
                        change={3}
                        format={(v) => `${v.toFixed(0)}%`}
                        subtitle="of messages delivered"
                    />
                ) : (
                    <OverviewMetric title="Replies" value={42} change={8} subtitle="STOP replies: 6" />
                )}
                <OverviewMetric
                    title="Clicked"
                    value={clicked * 100}
                    change={1}
                    format={(v) => `${v.toFixed(1)}%`}
                    subtitle="of messages delivered"
                />
            </div>
            <div className="grid grid-cols-2 gap-3 @min-[48rem]:grid-cols-4">
                <OverviewMetric
                    title="Bounced"
                    value={channel === 'email' ? 1.8 : 3.0}
                    change={42}
                    goodDirection="down"
                    format={(v) => `${v.toFixed(1)}%`}
                    subtitle="Daily limit drops above 5%"
                />
                <OverviewMetric
                    title="Spam complaints"
                    value={0.04}
                    change={-10}
                    goodDirection="down"
                    format={(v) => `${v.toFixed(2)}%`}
                    subtitle="Keep below 0.1%"
                />
                <OverviewMetric
                    title="Unsubscribed"
                    value={186}
                    change={5}
                    goodDirection="down"
                    subtitle="from marketing topics"
                />
                <OverviewMetric
                    title="Upgraded after a message"
                    value={64}
                    change={18}
                    subtitle="Paid plan within 7 days of a click"
                />
            </div>
            <section className="flex flex-col gap-2">
                <Heading size="sm">By type</Heading>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Type</TableHead>
                            <TableHead className="text-right">Sent</TableHead>
                            <TableHead className="text-right">Delivered</TableHead>
                            <TableHead className="text-right">Opened</TableHead>
                            <TableHead className="text-right">Clicked</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {KIND_ROWS.map(({ kind, label }) => {
                            const s = rows.find((row) => row.kind === kind)
                            const total = s ? sum(s.sent) : 0
                            return (
                                <TableRow key={kind}>
                                    <TableCell>{label}</TableCell>
                                    <TableCell className="text-right tabular-nums">{formatCount(total)}</TableCell>
                                    <TableCell className="text-right tabular-nums">
                                        {total ? percent(s!.deliveredRate) : '-'}
                                    </TableCell>
                                    <TableCell className="text-right tabular-nums">
                                        {total && channel !== 'sms' ? percent(s!.openRate) : '-'}
                                    </TableCell>
                                    <TableCell className="text-right tabular-nums">
                                        {total ? percent(s!.clickRate) : '-'}
                                    </TableCell>
                                </TableRow>
                            )
                        })}
                    </TableBody>
                </Table>
            </section>
            {channel === 'email' ? (
                <section className="flex flex-col gap-2">
                    <Heading size="sm">Broadcasts in the last 30 days</Heading>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Broadcast</TableHead>
                                <TableHead className="text-right">Sent</TableHead>
                                <TableHead className="text-right">Opened</TableHead>
                                <TableHead className="text-right">Clicked</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {TOP_BROADCASTS.map((b) => (
                                <TableRow key={b.name}>
                                    <TableCell>{b.name}</TableCell>
                                    <TableCell className="text-right tabular-nums">{formatCount(b.sent)}</TableCell>
                                    <TableCell className="text-right tabular-nums">{percent(b.opened)}</TableCell>
                                    <TableCell className="text-right tabular-nums">{percent(b.clicked)}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </section>
            ) : null}
        </div>
    )
}
