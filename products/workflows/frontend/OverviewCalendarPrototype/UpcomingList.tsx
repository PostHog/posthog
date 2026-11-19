// PROTOTYPE (throwaway): what goes out next, used by overviews A and C.
import { Card, CardGroup } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { EntryBadges } from './EntryBadges'
import { openInCalendar } from './openInCalendar'
import { TODAY, entriesBetween, formatCount } from './prototypeData'

export function UpcomingList({ days, limit }: { days: number; limit: number }): JSX.Element {
    const upcoming = entriesBetween(dayjs(), TODAY.add(days, 'day'))
        .filter((e) => e.state === 'scheduled' || e.state === 'paused')
        // A repeating workflow shows once, at its next run.
        .filter((e, i, all) => !e.repeatId || all.findIndex((other) => other.repeatId === e.repeatId) === i)
        .slice(0, limit)
    return (
        <CardGroup size="sm">
            {upcoming.map((entry) => (
                <Card key={entry.id} size="sm">
                    <button
                        type="button"
                        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1.5 text-left text-sm"
                        onClick={() => openInCalendar(entry.id)}
                    >
                        <span className="w-24 shrink-0 tabular-nums text-muted-foreground">
                            {entry.at.isSame(TODAY, 'day') ? 'Today' : entry.at.format('ddd, MMM D')}{' '}
                            {entry.at.format('H:mm')}
                        </span>
                        <span className="min-w-0 flex-1 truncate font-medium">{entry.name}</span>
                        <EntryBadges
                            kind={entry.kind}
                            state={entry.state === 'paused' ? 'paused' : undefined}
                            channel={entry.channel}
                            repeats={!!entry.repeatId}
                        />
                        <span className="w-24 shrink-0 text-right text-xs text-muted-foreground">
                            {formatCount(entry.people)} people
                        </span>
                    </button>
                </Card>
            ))}
        </CardGroup>
    )
}
