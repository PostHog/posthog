import { memo, useMemo } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SignalScoutRunSummary } from '../../../types'
import { ScoutRunBoxes } from './ScoutRunBoxes'

export const ScoutRosterRunBoxes = memo(function ScoutRosterRunBoxes({
    runs,
}: {
    runs: SignalScoutRunSummary[]
}): JSX.Element | null {
    const enabled = useFeatureFlag('SELF_DRIVING_USAGE_DISPLAY')
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
    return <ScoutRunBoxes runs={runs} costs={costs} />
})
