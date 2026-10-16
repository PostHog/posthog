export interface WorkspaceSetupStepProps {
    integrationId: number
    onComplete: () => void
    onSkip: () => void
}

export type WorkspaceSetupStepComponent = (props: WorkspaceSetupStepProps) => JSX.Element

/** The screen for each backend step key. A key the backend sends that is not here is not shown. */
export const WORKSPACE_SETUP_STEPS: Record<string, WorkspaceSetupStepComponent> = {}
