import posthog from 'posthog-js'

import type { WizardRunApi } from './generated/api.schemas'

/**
 * The Wizard CLI captures its own `wizard: *` events from the machine it runs on. This property
 * separates traffic from the cloud launchpad, so a report can tell the two surfaces apart.
 */
const SURFACE = 'cloud_launchpad'

export function reportWizardLaunchpadViewed(): void {
    posthog.capture('wizard launchpad viewed', { surface: SURFACE })
}

export function reportWizardLaunchpadRunOpened(run: WizardRunApi): void {
    posthog.capture('wizard launchpad run opened', {
        surface: SURFACE,
        run_environment: run.environment,
        run_status: run.status,
        program_id: run.program.id,
    })
}

export function reportWizardLaunchpadRunStarted(run: WizardRunApi): void {
    posthog.capture('wizard launchpad run started', {
        surface: SURFACE,
        run_environment: run.environment,
        program_id: run.program.id,
        workspace_type: run.workspace.type,
    })
}
