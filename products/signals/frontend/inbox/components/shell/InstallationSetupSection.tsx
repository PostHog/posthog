import { useValues } from 'kea'
import { useMountedLogic } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'

import { SettingsSection } from '../tabs/SettingsSection'
import { InstallationCard } from './InstallationCard'
import { SetupSection } from './SetupSection'

/**
 * The "Installation" block of the Settings tab, present only while a wizard run is in flight.
 * Renders its own section wrapper so the heading disappears with the run.
 */
export function InstallationSetupSection(): JSX.Element | null {
    const redesign = useFeatureFlag('INBOX_REDESIGN')
    // The detector's cheap poll is what tells us a run exists at all; mounting it here means the
    // tab doesn't depend on the FAB being rendered to find the run.
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { shouldStream, activeWorkflowId } = useValues(wizardActiveSessionDetectorLogic)

    if (!shouldStream || !activeWorkflowId) {
        return null
    }

    if (!redesign) {
        return (
            <SetupSection title="Installation">
                <InstallationCard workflowId={activeWorkflowId} />
            </SetupSection>
        )
    }
    return (
        <SettingsSection title="Installation" description="The setup agent is still running in your repository.">
            <InstallationCard workflowId={activeWorkflowId} />
        </SettingsSection>
    )
}
