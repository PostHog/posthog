import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import type { ScoutRosterRow } from '../../../utils/scoutGroups'
import { ScoutRosterCard } from './ScoutRosterCard'

function cards(rows: ScoutRosterRow[]): JSX.Element[] {
    return rows.map((row) => <ScoutRosterCard key={row.config.id} row={row} />)
}

/** The filtered, sorted troop as one column of cards, or a one-line notice when nothing matches. */
export function ScoutsRosterList(): JSX.Element {
    const { rosterScouts, rosterSections, scoutKindFilter } = useValues(scoutFleetLogic)
    const [closedOpen, setClosedOpen] = useState(false)

    if (rosterScouts.length === 0) {
        return <p className="m-0 px-1 py-2 text-sm text-tertiary">No scouts match the current filters.</p>
    }

    const { openGoals, closedGoals, scouts } = rosterSections
    const collapseClosed = scoutKindFilter === 'goals'

    return (
        <div className="flex flex-col gap-1.5">
            {cards(openGoals)}
            {collapseClosed && closedGoals.length > 0 && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-start"
                    onClick={() => setClosedOpen(!closedOpen)}
                    data-attr="goal-scouts-closed"
                >
                    {closedOpen ? 'Hide' : 'Show'} closed goals ({closedGoals.length})
                </LemonButton>
            )}
            {(!collapseClosed || closedOpen) && cards(closedGoals)}
            {cards(scouts)}
        </div>
    )
}
