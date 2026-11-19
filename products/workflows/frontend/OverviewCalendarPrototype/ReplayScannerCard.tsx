// PROTOTYPE (throwaway): a replay vision scanner that watches the sessions after a message, with what it found,
// and scanners you can set up next.
import clsx from 'clsx'

import { IconPlus, IconRewindPlay } from '@posthog/icons'
import { Badge, Button } from '@posthog/quill'

import { ChartCard } from './ChartCard'
import { SCANNER, SUGGESTED_SCANNERS } from './insightsData'

const TONE_CLASS = {
    positive: 'bg-success-foreground',
    negative: 'bg-destructive-foreground',
    neutral: 'bg-warning-foreground',
}

export function ReplayScannerCard(): JSX.Element {
    return (
        <ChartCard
            title="Replay vision"
            description="Scanners watch the sessions that follow a message and report what they see."
            action={<Badge variant="info">1 running</Badge>}
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-2 rounded-md border p-3">
                    <div className="flex items-start gap-2">
                        <IconRewindPlay className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                        <div className="flex min-w-0 flex-col">
                            <span className="text-sm font-medium">{SCANNER.name}</span>
                            <span className="text-xs text-muted-foreground">{SCANNER.question}</span>
                        </div>
                    </div>
                    <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                        {SCANNER.observations.map((o) => (
                            <li key={o.text} className="flex items-center gap-2 text-sm">
                                <span
                                    aria-hidden
                                    className={clsx('size-2 shrink-0 rounded-full', TONE_CLASS[o.tone])}
                                />
                                <span className="min-w-0 flex-1">{o.text}</span>
                                <Button variant="link" size="inline">
                                    {o.sessions} sessions
                                </Button>
                            </li>
                        ))}
                    </ul>
                    <span className="text-xs text-muted-foreground">
                        Watched {SCANNER.sessions} sessions after a click
                    </span>
                </div>
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-medium text-muted-foreground">Set up a scanner</span>
                    {SUGGESTED_SCANNERS.map((s) => (
                        <Button key={s} variant="outline" className="justify-start">
                            <IconPlus />
                            <span className="truncate">{s}</span>
                        </Button>
                    ))}
                </div>
            </div>
        </ChartCard>
    )
}
