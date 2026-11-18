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
            {/* The cadence is a changing string beside a sibling, so it gets its own element —
                see Rule 7 in frontend/src/AGENTS.md. */}
            <span>{scoutCadenceLabel(config)}</span>
            {scoutCadenceNamesClockTime(config) && (
                <>
                    {' '}
                    {/* The hint's tooltip holds a settings link, and the tooltip renders in a portal
                        that still sits under this node in the React tree. A surrounding row or card
                        link would otherwise take the click and navigate itself. */}
                    <span onClick={(event) => event.stopPropagation()}>
                        <ProjectTimezoneHint />
                    </span>
                </>
            )}
        </>
    )
}
