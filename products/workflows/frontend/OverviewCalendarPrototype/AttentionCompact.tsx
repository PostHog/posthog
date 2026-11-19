// PROTOTYPE (throwaway): the needs-attention list from overview A, shrunk to one line per problem.
import { IconWarning } from '@posthog/icons'
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from '@posthog/quill'

import { openInCalendar } from './openInCalendar'
import { SENDING_DOMAIN } from './prototypeData'

const ITEMS: { id: string; tone: 'destructive' | 'warning'; text: string; action: string; onAction?: () => void }[] = [
    { id: 'domain', tone: 'destructive', text: `${SENDING_DOMAIN} fails its DKIM check`, action: 'Fix' },
    { id: 'sms', tone: 'warning', text: '38 SMS messages failed yesterday', action: 'Logs' },
    { id: 'bounce', tone: 'warning', text: 'Bounce rate 4.1% this week', action: 'View' },
    {
        id: 'paused',
        tone: 'warning',
        text: 'Partner program invite is paused',
        action: 'Open',
        onAction: () => openInCalendar('b-paused'),
    },
]

export function AttentionCompact(): JSX.Element {
    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    Needs attention <Badge variant="destructive">{ITEMS.length}</Badge>
                </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-1">
                {ITEMS.map((item) => (
                    <div key={item.id} className="flex items-center gap-2 text-xs">
                        <IconWarning
                            className={
                                item.tone === 'destructive'
                                    ? 'size-3.5 shrink-0 text-destructive-foreground'
                                    : 'size-3.5 shrink-0 text-warning-foreground'
                            }
                        />
                        <span className="min-w-0 flex-1 truncate">{item.text}</span>
                        <Button variant="link" size="inline" onClick={item.onAction}>
                            {item.action}
                        </Button>
                    </div>
                ))}
            </CardContent>
        </Card>
    )
}
