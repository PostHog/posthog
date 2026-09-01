import { WizardRunApi, WizardRunStageEnumApi } from './generated/api.schemas'
import { wizardRunErrorDetails } from './runs/wizardRunErrorCatalog'

export const MAX_RENDERED_WIZARD_DIFF_BYTES = 2 * 1024 * 1024
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

export function wizardRunCanCancel(run: WizardRunApi, currentUserId: number | null): boolean {
    // The API only lets the run's creator cancel it, so hide the control for everyone else.
    // A run with no creator has no owner who can cancel it, so hide it there too.
    return wizardRunIsActive(run) && run.created_by_id !== null && run.created_by_id === currentUserId
}

const FAILURE_STAGE_BY_ERROR_CODE: Record<string, WizardRunStageEnumApi> = {
    dispatch_failed: WizardRunStageEnumApi.Dispatching,
    provisioning_failed: WizardRunStageEnumApi.Provisioning,
    repository_access_failed: WizardRunStageEnumApi.PreparingWorkspace,
    workspace_preparation_failed: WizardRunStageEnumApi.PreparingWorkspace,
    timeout: WizardRunStageEnumApi.ExecutingWizard,
    artifact_creation_failed: WizardRunStageEnumApi.CreatingArtifacts,
}

export function wizardRunFailureStage(run: WizardRunApi): WizardRunStageEnumApi {
    if (run.stage) {
        return run.stage
    }
    return FAILURE_STAGE_BY_ERROR_CODE[run.error_code ?? ''] ?? WizardRunStageEnumApi.ExecutingWizard
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
