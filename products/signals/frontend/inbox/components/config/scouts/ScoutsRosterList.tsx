import { useValues } from 'kea'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutRosterCard } from './ScoutRosterCard'

/** The filtered, sorted troop as one column of cards, or a one-line notice when nothing matches. */
export function ScoutsRosterList(): JSX.Element {
    const { rosterScouts } = useValues(scoutFleetLogic)

    if (rosterScouts.length === 0) {
        return <p className="m-0 px-1 py-2 text-sm text-tertiary">No scouts match the current filters.</p>
    }

    return (
        <div className="flex flex-col gap-1.5">
            {rosterScouts.map((row) => (
                <ScoutRosterCard key={row.config.id} row={row} />
            ))}
        </div>
    )
}
