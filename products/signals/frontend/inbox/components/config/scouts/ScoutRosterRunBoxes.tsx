import { useValues } from 'kea'
import { memo, useMemo } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SignalScoutRunSummary } from '../../../types'
import { ScoutRunBoxes } from './ScoutRunBoxes'

export const ScoutRosterRunBoxes = memo(function ScoutRosterRunBoxes({
    runs,
}: {
    runs: SignalScoutRunSummary[]
}): JSX.Element | null {
    const enabled = useFeatureFlag('SELF_DRIVING_USAGE')
    const { scoutRunCostsByScout, expensiveRunCostThreshold } = useValues(scoutFleetLogic)
    const costs = useMemo(
        () =>
            enabled
                ? new Map(
                      runs.flatMap((run) =>
                          run.total_spend == null ? [] : [[run.run_id, run.total_spend / 100] as const]
                      )
                  )
                : undefined,
        [runs, enabled]
    )
    return (
        <ScoutRunBoxes
            runs={runs}
            costs={enabled ? costs : scoutRunCostsByScout.get(runs[0]?.skill_name ?? '')}
            costThreshold={enabled ? undefined : expensiveRunCostThreshold}
        />
    )
})
