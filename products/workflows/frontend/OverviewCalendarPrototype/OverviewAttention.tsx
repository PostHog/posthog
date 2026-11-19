// PROTOTYPE (throwaway): overview A, attention first. What needs you now, what goes out next, and your drafts.
// Numbers come last, in one line.
import { IconWarning } from '@posthog/icons'
import { Badge, Button, Card, CardGroup, Heading } from '@posthog/quill'

import { EntryBadges } from './EntryBadges'
import { openInCalendar } from './openInCalendar'
import { DRAFTS, SENDING_DOMAIN, SERIES, percent, sum, formatCount } from './prototypeData'
import { UpcomingList } from './UpcomingList'

interface AttentionItem {
    id: string
    tone: 'destructive' | 'warning'
    title: string
    detail: string
    action: string
    onAction?: () => void
}

const ITEMS: AttentionItem[] = [
    {
        id: 'domain',
        tone: 'destructive',
        title: `The sending domain ${SENDING_DOMAIN} failed its DKIM check`,
        detail: 'Pricing page survey stopped after 1,204 of 5,000 messages. Fix the DNS record, then resume it.',
        action: 'Fix sending domain',
    },
    {
        id: 'sms',
        tone: 'warning',
        title: 'Trial ending reminder: 38 messages failed in the last 24 hours',
        detail: 'The carrier rejected 38 phone numbers on the SMS step.',
        action: 'View logs',
    },
    {
        id: 'bounce',
        tone: 'warning',
        title: 'Bounce rate is 4.1% this week, up from 1.2%',
        detail: 'Your daily limit goes down when the bounce rate passes 5%.',
        action: 'Open deliverability',
    },
    {
        id: 'paused',
        tone: 'warning',
        title: 'Partner program invite is paused',
        detail: 'It was due in 6 days. Resume it or move it on the calendar.',
        action: 'Open on calendar',
        onAction: () => openInCalendar('b-paused', 'D'),
    },
]

export function OverviewAttention(): JSX.Element {
    const email = SERIES.filter((s) => s.channel === 'email')
    const sent = sum(email.flatMap((s) => s.sent))
    return (
        <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    <Heading size="sm">Needs attention</Heading>
                    <Badge variant="destructive">{ITEMS.length}</Badge>
                </div>
                <CardGroup size="sm">
                    {ITEMS.map((item) => (
                        <Card key={item.id} size="sm">
                            <div className="flex flex-wrap items-center gap-3 px-2 py-2">
                                <IconWarning
                                    className={
                                        item.tone === 'destructive'
                                            ? 'text-destructive-foreground'
                                            : 'text-warning-foreground'
                                    }
                                />
                                <div className="flex min-w-0 flex-1 flex-col">
                                    <span className="text-sm font-medium">{item.title}</span>
                                    <span className="text-xs text-muted-foreground">{item.detail}</span>
                                </div>
                                <Button variant="outline" onClick={item.onAction}>
                                    {item.action}
                                </Button>
                            </div>
                        </Card>
                    ))}
                </CardGroup>
            </section>
            <div className="grid gap-6 @min-[56rem]:grid-cols-[3fr_2fr]">
                <section className="flex min-w-0 flex-col gap-2">
                    <div className="flex items-center justify-between">
                        <Heading size="sm">Goes out in the next 7 days</Heading>
                        <Button variant="link" onClick={() => openInCalendar(undefined, 'F')}>
                            Open calendar
                        </Button>
                    </div>
                    <UpcomingList days={7} limit={6} />
                </section>
                <section className="flex min-w-0 flex-col gap-2">
                    <Heading size="sm">Drafts</Heading>
                    <CardGroup size="sm">
                        {DRAFTS.map((draft) => (
                            <Card key={draft.id} size="sm">
                                <button
                                    type="button"
                                    className="flex w-full flex-col gap-1 px-2 py-1.5 text-left text-sm"
                                >
                                    <span className="font-medium">{draft.name}</span>
                                    <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                        <EntryBadges kind={draft.kind} state="draft" />
                                        Edited {draft.edited} by {draft.by}
                                    </span>
                                </button>
                            </Card>
                        ))}
                    </CardGroup>
                </section>
            </div>
            <section className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t pt-3 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Last 30 days, email</span>
                <span>{formatCount(sent)} messages sent</span>
                <span>{percent(0.986)} delivered</span>
                <span>{percent(0.52)} opened</span>
                <span>{percent(0.19)} clicked</span>
                <Button variant="link">See performance</Button>
            </section>
        </div>
    )
}
