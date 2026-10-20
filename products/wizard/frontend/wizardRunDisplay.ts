import { WizardRunApi, WizardRunStageEnumApi } from './generated/api.schemas'
import { wizardRunErrorDetails } from './runs/wizardRunErrorCatalog'

export const MAX_RENDERED_WIZARD_DIFF_BYTES = 2 * 1024 * 1024
// Byte size does not bound DOM nodes: many short lines can pass the byte cap and still stall the page.
export const MAX_RENDERED_WIZARD_DIFF_LINES = 20_000
export const WIZARD_LOCAL_RUNS_VISIBLE = false

export function wizardRunDiffCanRender(sizeBytes: number): boolean {
    return sizeBytes <= MAX_RENDERED_WIZARD_DIFF_BYTES
}

export function wizardWorkspaceLabel(run: WizardRunApi): string {
    return run.workspace.type === 'git_repository' ? run.workspace.repository : run.workspace.project_name
}

export function wizardCommand(packageVersion: string, command: readonly string[]): string {
    return ['npx', `@posthog/wizard@${packageVersion}`, ...command].join(' ')
}

export function wizardRunIsActive(run: WizardRunApi): boolean {
    return run.status === 'created' || run.status === 'running'
}

export function wizardRunTerminalLabel(status: WizardRunApi['status']): string {
    switch (status) {
        case 'completed':
            return 'Completed'
        case 'failed':
            return 'Failed'
        case 'cancelled':
            return 'Canceled'
        default:
            return 'Finished'
    }
}

export function wizardRunCanCancel(run: WizardRunApi, currentUserId: number | null): boolean {
    // The server cannot stop a local process, even when it marks that run canceled.
    return (
        run.environment === 'cloud' &&
        wizardRunIsActive(run) &&
        run.created_by_id !== null &&
        run.created_by_id === currentUserId
    )
}

const FAILURE_STAGE_BY_ERROR_CODE: Record<string, WizardRunStageEnumApi> = {
    dispatch_failed: WizardRunStageEnumApi.Dispatching,
    provisioning_failed: WizardRunStageEnumApi.Provisioning,
    repository_access_failed: WizardRunStageEnumApi.PreparingWorkspace,
    workspace_preparation_failed: WizardRunStageEnumApi.PreparingWorkspace,
    timeout: WizardRunStageEnumApi.ExecutingWizard,
    artifact_creation_failed: WizardRunStageEnumApi.CreatingArtifacts,
}

export function wizardRunFailureStage(run: WizardRunApi): WizardRunStageEnumApi | null {
    if (run.stage) {
        return run.stage
    }

    // Timeouts are recorded with a generic code regardless of which step ran out of time,
    // so the failed stage is unknowable and the failure can only be shown at run level.
    if (run.error_code === 'timeout') {
        return null
    }

    return FAILURE_STAGE_BY_ERROR_CODE[run.error_code ?? ''] ?? WizardRunStageEnumApi.ExecutingWizard
}

export type WizardRunProgressState = 'complete' | 'active' | 'pending' | 'failed'

export function wizardRunStagePosition(run: WizardRunApi): number {
    if (run.status === 'completed') {
        return 4
    }
    if (run.status === 'created') {
        return 0
    }

    const stage = run.status === 'failed' ? wizardRunFailureStage(run) : run.stage

    switch (stage) {
        case 'dispatching':
        case 'provisioning':
            return 0
        case 'preparing_workspace':
            return 1
        case 'executing_wizard':
            return 2
        case 'creating_artifacts':
            return 3
        default:
            return run.status === 'running' ? 2 : 0
    }
}

export function wizardRunProgressState(run: WizardRunApi, step: number): WizardRunProgressState {
    if (run.status === 'cancelled') {
        return step === 0 ? 'complete' : 'pending'
    }

    const position = wizardRunStagePosition(run)

    if (run.status === 'failed') {
        if (wizardRunFailureStage(run) === null) {
            return step === 0 ? 'complete' : 'pending'
        }
        if (position === step) {
            return 'failed'
        }
    }
    if (position > step) {
        return 'complete'
    }
    if (position === step && run.status !== 'completed') {
        return 'active'
    }
    return 'pending'
}

export function wizardGithubRepositoryUrl(repository: string): string {
    return `https://github.com/${repository}`
}

export function formatArtifactSize(sizeBytes: number): string {
    if (sizeBytes < 1024) {
        return `${sizeBytes} B`
    }
    if (sizeBytes < 1024 * 1024) {
        return `${(sizeBytes / 1024).toFixed(1)} KB`
    }
    return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`
}

export function wizardRunCurrentState(run: WizardRunApi): string {
    if (run.status === 'completed') {
        return 'Completed successfully'
    }
    if (run.status === 'failed') {
        return wizardRunErrorDetails(run.error_code, run.error_message).title
    }
    if (run.status === 'cancelled') {
        return 'Run canceled'
    }

    switch (run.stage) {
        case WizardRunStageEnumApi.Dispatching:
            return 'Starting the Wizard Worker'
        case WizardRunStageEnumApi.Provisioning:
            return 'Provisioning the Wizard Worker'
        case WizardRunStageEnumApi.PreparingWorkspace:
            return 'Preparing the repository'
        case WizardRunStageEnumApi.ExecutingWizard:
            return run.program.name.endsWith('audit')
                ? `Running the ${run.program.name}`
                : `Running ${run.program.name}`
        case WizardRunStageEnumApi.CreatingArtifacts:
            return 'Creating run artifacts'
        default:
            return run.status === 'running' ? 'Running the Wizard' : 'Starting the Wizard run'
    }
}
