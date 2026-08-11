import { useValues } from 'kea'
import { useMountedLogic } from 'kea'

import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'

import { InstallationCard } from './InstallationCard'
import { SetupSection } from './SetupSection'

/**
 * The "Installation" block of the inbox setup column, present only while a wizard run is in flight.
 * Renders its own section wrapper so the heading disappears with the run.
 */
export function InstallationSetupSection(): JSX.Element | null {
    // The detector's cheap poll is what tells us a run exists at all; mounting it here means the
    // rail doesn't depend on the FAB being rendered to find the run.
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { shouldStream, activeWorkflowId } = useValues(wizardActiveSessionDetectorLogic)

    if (!shouldStream || !activeWorkflowId) {
        return null
    }

    return (
        <SetupSection title="Installation">
            <InstallationCard workflowId={activeWorkflowId} />
        </SetupSection>
    )
}
