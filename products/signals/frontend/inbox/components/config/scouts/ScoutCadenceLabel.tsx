import { ProjectTimezoneHint } from 'lib/components/ScheduledRunStatus'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutCadenceLabel, scoutCadenceNamesClockTime } from '../../../utils/scoutGroups'

/**
 * How often the scout runs. A cadence that states a clock time carries the project timezone next to
 * it, because that is the timezone the coordinator resolves the schedule in — without it a reader
 * in another timezone reads the time as their own and thinks the scout runs late.
 */
export function ScoutCadenceLabel({ config }: { config: SignalScoutConfig }): JSX.Element {
    return (
        <>
            {scoutCadenceLabel(config)}
            {scoutCadenceNamesClockTime(config) && (
                <>
                    {' '}
                    <ProjectTimezoneHint />
                </>
            )}
        </>
    )
}
