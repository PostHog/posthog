import { useValues } from 'kea'
import { memo } from 'react'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SignalScoutRunSummary } from '../../../types'
import { ScoutRunBoxes } from './ScoutRunBoxes'

/**
 * A scout's run strip with that scout's costs. The cost subscription lives here, not in the card or
 * table that holds the strip, so a cost batch re-renders this small component and not the whole row.
 * `ScoutRunBoxes` then skips its render when the scout's cost slice kept its reference.
 */
export const ScoutRosterRunBoxes = memo(function ScoutRosterRunBoxes({
    skillName,
    runs,
}: {
    skillName: string
    runs: SignalScoutRunSummary[]
}): JSX.Element | null {
    const { scoutRunCostsByScout, expensiveRunCostThreshold } = useValues(scoutFleetLogic)
    return (
        <ScoutRunBoxes
            runs={runs}
            costs={scoutRunCostsByScout.get(skillName)}
            costThreshold={expensiveRunCostThreshold}
        />
    )
})
