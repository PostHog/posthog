import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { SdkProfileSection } from '../../setupInspector/sections/SdkProfileSection'
import { TeamDefaultsSection } from '../../setupInspector/sections/TeamDefaultsSection'
import { experimentHealthDebugLogic } from './experimentHealthDebugLogic'

export function HealthDebugProjectTab(): JSX.Element {
    const { experimentId } = useValues(experimentLogic)
    const { healthInputs, healthInputsLoading } = useValues(experimentHealthDebugLogic({ experimentId }))

    if (!healthInputs) {
        return healthInputsLoading ? (
            <LemonSkeleton repeat={6} className="h-6" />
        ) : (
            <p className="text-secondary mb-0">The project facts did not load. Reload the inputs to try again.</p>
        )
    }
    return (
        <div className="flex flex-col gap-4">
            <p className="text-secondary text-sm mb-0">
                Project-wide facts, read by the same providers as the setup context. No check reads them yet. They help
                explain a finding, for example when flags are evaluated outside the flag service.
            </p>
            <SdkProfileSection
                section={healthInputs.project.sdk_profile}
                skippedMessage="Skipped, because you may not query events or are denied a property it reads."
            />
            <TeamDefaultsSection section={healthInputs.project.team_defaults} />
        </div>
    )
}
