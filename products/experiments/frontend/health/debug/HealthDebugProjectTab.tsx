import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { SdkProfileSection } from '../../setupInspector/sections/SdkProfileSection'
import { TeamDefaultsSection } from '../../setupInspector/sections/TeamDefaultsSection'
import { experimentHealthDebugLogic } from './experimentHealthDebugLogic'
import { PROJECT_FACTS_DESCRIPTION, PROJECT_FACTS_NOT_LOADED, SDK_PROFILE_SKIPPED } from './healthDebugCopy'

export function HealthDebugProjectTab(): JSX.Element {
    const { experimentId } = useValues(experimentLogic)
    const { healthInputs, healthInputsLoading } = useValues(experimentHealthDebugLogic({ experimentId }))

    if (!healthInputs) {
        return healthInputsLoading ? (
            <LemonSkeleton repeat={6} className="h-6" />
        ) : (
            <p className="text-secondary mb-0">{PROJECT_FACTS_NOT_LOADED}</p>
        )
    }
    return (
        <div className="flex flex-col gap-4">
            <p className="text-secondary text-sm mb-0">{PROJECT_FACTS_DESCRIPTION}</p>
            <SdkProfileSection section={healthInputs.project.sdk_profile} skippedMessage={SDK_PROFILE_SKIPPED} />
            <TeamDefaultsSection section={healthInputs.project.team_defaults} />
        </div>
    )
}
