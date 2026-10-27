import type { WorkspaceSetupStepKey } from './slackAppWorkspaceSetupLogic'
import { AIConsentStep } from './steps/AIConsentStep'
import { DefaultProjectStep } from './steps/DefaultProjectStep'

export function SlackAppWorkspaceSetupStep({ step }: { step: WorkspaceSetupStepKey }): JSX.Element {
    switch (step) {
        case 'ai_consent':
            return <AIConsentStep />
        case 'default_project':
            return <DefaultProjectStep />
    }
}
