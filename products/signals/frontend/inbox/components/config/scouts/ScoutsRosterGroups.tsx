import { useValues } from 'kea'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutsRosterGroup } from './ScoutsRosterGroup'

export function ScoutsRosterGroups(): JSX.Element {
    const { rosterBuckets } = useValues(scoutFleetLogic)

    if (rosterBuckets.length === 0) {
        return <span className="px-6 py-6 text-sm text-muted">No scouts match the current filters.</span>
    }

    return (
        <div className="flex flex-col">
            {rosterBuckets.map((bucket, index) => (
                <ScoutsRosterGroup key={bucket.key} bucket={bucket} showHeader={index === 0} />
            ))}
        </div>
    )
}
