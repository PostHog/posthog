import * as peekOverPng from '@posthog/brand/hoggies/png/peek-over'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { urls } from 'scenes/urls'

import { adventPalette } from '../adventPalette'
import { AdventSnow } from '../AdventSnow'
import { AdventVillageArt } from '../AdventVillageArt'
import { reportAdventEntryClicked } from './adventEntryEvents'
import { AdventEntryPhase } from './adventEntryPhase'
import { AdventTreeIcon } from './AdventTreeIcon'
import { useAdventHoverSnow } from './useAdventHoverSnow'

function phaseCopy(phase: AdventEntryPhase): { text: string; action: string } {
    switch (phase.status) {
        case 'soon':
            return {
                text: 'The first door opens on December 1. Each door holds a hedgehog and a Workflows tip.',
                action: 'Open the calendar',
            }
        case 'open':
            return {
                text: 'A new door opens each day until December 24. Each one holds a hedgehog and a Workflows tip.',
                action: `Open door ${phase.day}`,
            }
        case 'over':
            return {
                text: 'All 24 doors are open. Each one holds a hedgehog and a Workflows tip.',
                action: 'Open the calendar',
            }
    }
}

export function AdventEntryCard({ phase }: { phase: AdventEntryPhase }): JSX.Element {
    const hoverSnow = useAdventHoverSnow()
    const copy = phaseCopy(phase)
    return (
        <LemonCard
            hoverEffect={false}
            className="@container/advent-entry flex min-h-28 overflow-hidden p-0"
            data-attr="advent-entry-card"
        >
            <div className="flex min-w-0 flex-1 flex-col items-start justify-center gap-2 px-4 py-3">
                <h3 className="m-0 flex items-center gap-2 text-base font-semibold">
                    <AdventTreeIcon className="size-5 shrink-0 text-success" />
                    The Workflows advent calendar
                </h3>
                <p className="m-0 text-secondary">{copy.text}</p>
                <span className="inline-flex" {...hoverSnow}>
                    <LemonButton
                        type="primary"
                        size="small"
                        to={urls.workflowsAdventCalendar()}
                        onClick={() => reportAdventEntryClicked('card')}
                        data-attr="advent-entry-card-open"
                    >
                        {copy.action}
                    </LemonButton>
                </span>
            </div>
            <div className="relative hidden w-2/5 max-w-[32rem] shrink-0 overflow-hidden @min-[40rem]/advent-entry:block">
                <div className="absolute inset-x-0 top-0 aspect-[16/9] -translate-y-[15%]">
                    <AdventVillageArt palette={adventPalette()} />
                </div>
                <AdventSnow />
                <img
                    src={peekOverPng.src}
                    alt=""
                    className="pointer-events-none absolute -bottom-3 left-4 z-[5] w-24"
                />
            </div>
        </LemonCard>
    )
}
