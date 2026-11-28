import './AdventEntryCard.scss'

import { useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { ADVENT_LAST_DAY } from '../adventContent'
import { AdventSnow } from '../AdventSnow'
import { AdventEntryDoor } from './AdventEntryDoor'
import { reportAdventEntryClicked, reportAdventEntryMiddleClicked } from './adventEntryEvents'
import { adventEntryProgressLogic } from './adventEntryProgressLogic'
import { adventEntrySummary } from './adventEntrySummary'
import { AdventTreeIcon } from './AdventTreeIcon'
import { useAdventHoverSnow } from './useAdventHoverSnow'

const DAYS = Array.from({ length: ADVENT_LAST_DAY }, (_, index) => index + 1)

function rowFit(opened: number): 'few' | 'some' | 'many' {
    return opened <= 4 ? 'few' : opened <= 12 ? 'some' : 'many'
}

export function AdventEntryCard(): JSX.Element {
    const hoverSnow = useAdventHoverSnow()
    const { doors, nextDoorDay, phase } = useValues(adventEntryProgressLogic)
    const summary = adventEntrySummary(doors, phase)
    const opened = doors?.filter((door) => door.status === 'open').length ?? 0
    return (
        <div className={cn('AdventEntryCard', `AdventEntryCard--${rowFit(opened)}`)} data-attr="advent-entry-card">
            <AdventSnow />
            <div className="AdventEntryCard__content">
                <div className="AdventEntryCard__title">
                    <h3 className="m-0 flex items-center gap-2 text-base font-semibold">
                        <AdventTreeIcon className="size-5 shrink-0 text-success" />
                        Workflows Advent Calendar
                    </h3>
                    {phase.status === 'soon' && (
                        <p className="AdventEntryCard__subline m-0 text-[0.8125rem]">The first door opens December 1</p>
                    )}
                </div>
                {summary && <p className="sr-only">{summary}</p>}
                <div className="AdventEntryCard__doors" aria-hidden>
                    {DAYS.map((day) => (
                        <AdventEntryDoor
                            key={day}
                            day={day}
                            door={doors?.[day - 1] ?? null}
                            isToday={phase.status === 'open' && day === phase.day}
                        />
                    ))}
                </div>
                <span className="inline-flex shrink-0" {...hoverSnow}>
                    <LemonButton
                        type="primary"
                        to={urls.workflowsAdventCalendar()}
                        onClickCapture={() => reportAdventEntryClicked('card')}
                        onAuxClick={(event) => reportAdventEntryMiddleClicked(event, 'card')}
                        data-attr="advent-entry-card-open"
                    >
                        {nextDoorDay ? `Open door ${nextDoorDay}` : 'Open the calendar'}
                    </LemonButton>
                </span>
            </div>
        </div>
    )
}
