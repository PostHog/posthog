import { useValues } from 'kea'
import { ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { RelevancePilotContent } from './RelevancePilotContent'

export function RelevancePilot({ children }: { children: ReactNode }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.SIGNALS_RELEVANCE_PILOT] ? (
        <RelevancePilotContent key={currentTeamId}>{children}</RelevancePilotContent>
    ) : (
        <>{children}</>
    )
}
