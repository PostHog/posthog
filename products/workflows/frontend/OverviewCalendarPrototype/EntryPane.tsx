// PROTOTYPE (throwaway): what opens when you click an entry on the calendar.
import { IconX } from '@posthog/icons'
import { Button, Card, CardContent, CardHeader, CardTitle, Separator } from '@posthog/quill'

import { EntryBadges } from './EntryBadges'
import { CHANNEL_LABEL, CalendarEntry, REPEATING, TIMEZONE_LABEL, formatCount, percent } from './prototypeData'

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between gap-4 text-sm">
            <span className="text-muted-foreground">{label}</span>
            <span className="text-right">{children}</span>
        </div>
    )
}

export function EntryPane({ entry, onClose }: { entry: CalendarEntry; onClose: () => void }): JSX.Element {
    const repeat = entry.repeatId ? REPEATING.find((r) => r.id === entry.repeatId) : undefined
    const r = entry.results
    return (
        <Card className="w-full @min-[64rem]:w-80 shrink-0 self-start">
            <CardHeader>
                <div className="flex items-start justify-between gap-2">
                    <CardTitle>{entry.name}</CardTitle>
                    <Button size="icon-sm" aria-label="Close" tooltip="Close" onClick={onClose}>
                        <IconX />
                    </Button>
                </div>
                <EntryBadges kind={entry.kind} state={entry.state} channel={entry.channel} repeats={!!repeat} />
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
                <Row label={entry.state === 'sent' || entry.state === 'failed' ? 'Sent' : 'Sends'}>
                    {entry.at.format('ddd, MMM D [at] H:mm')} {TIMEZONE_LABEL}
                </Row>
                {repeat ? <Row label="Repeats">{repeat.rule}</Row> : null}
                <Row label="Channel">{CHANNEL_LABEL[entry.channel]}</Row>
                <Row label="Audience">{entry.audience}</Row>
                <Row label="People">{formatCount(entry.people)}</Row>
                <Row label="Created by">{entry.createdBy}</Row>
                {entry.error ? (
                    <div className="rounded-md bg-destructive p-2 text-sm text-destructive-foreground">
                        {entry.error}
                    </div>
                ) : null}
                {r ? (
                    <>
                        <Separator />
                        <Row label="Delivered">
                            {formatCount(r.delivered)} ({percent(r.delivered / r.sent)})
                        </Row>
                        {entry.channel !== 'sms' ? (
                            <Row label="Opened">
                                {formatCount(r.opened)} ({percent(r.opened / r.delivered)})
                            </Row>
                        ) : null}
                        <Row label="Clicked">
                            {formatCount(r.clicked)} ({percent(r.clicked / r.delivered)})
                        </Row>
                        <Row label="Bounced">{formatCount(r.bounced)}</Row>
                        <Row label="Unsubscribed">{formatCount(r.unsubscribed)}</Row>
                    </>
                ) : null}
                <Separator />
                <div className="flex flex-wrap gap-2">
                    {r ? (
                        <>
                            <Button variant="outline">Metrics</Button>
                            <Button variant="outline">Logs</Button>
                        </>
                    ) : (
                        <>
                            <Button variant="outline">Preview</Button>
                            {entry.state === 'scheduled' && !repeat ? (
                                <Button variant="outline">Change time</Button>
                            ) : null}
                        </>
                    )}
                    <Button variant="primary">Open {entry.kind === 'broadcast' ? 'broadcast' : 'workflow'}</Button>
                </div>
            </CardContent>
        </Card>
    )
}
