import { elapsedSecondsFrom } from 'lib/utils/datetime'

import { WizardRunApi, WizardRunStageEnumApi } from '../generated/api.schemas'
import type { WizardRunTaskApi } from '../generated/api.schemas'
import { wizardRunErrorDetails } from './wizardRunErrorCatalog'

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

export enum WizardRunProgressStep {
    Starting = 'starting',
    PreparingWorkspace = 'preparing_workspace',
    ExecutingWizard = 'executing_wizard',
    CreatingArtifacts = 'creating_artifacts',
}

export const WIZARD_RUN_PROGRESS_STEPS = [
    WizardRunProgressStep.Starting,
    WizardRunProgressStep.PreparingWorkspace,
    WizardRunProgressStep.ExecutingWizard,
    WizardRunProgressStep.CreatingArtifacts,
] as const

export type WizardRunProgressState = 'complete' | 'active' | 'pending' | 'failed'

function progressStepForStage(stage: WizardRunStageEnumApi | null): WizardRunProgressStep | null {
    switch (stage) {
        case WizardRunStageEnumApi.Dispatching:
        case WizardRunStageEnumApi.Provisioning:
            return WizardRunProgressStep.Starting
        case WizardRunStageEnumApi.PreparingWorkspace:
            return WizardRunProgressStep.PreparingWorkspace
        case WizardRunStageEnumApi.ExecutingWizard:
            return WizardRunProgressStep.ExecutingWizard
        case WizardRunStageEnumApi.CreatingArtifacts:
            return WizardRunProgressStep.CreatingArtifacts
        default:
            return null
    }
}

export function wizardRunProgressStep(run: WizardRunApi): WizardRunProgressStep | null {
    if (run.status === 'completed' || run.status === 'cancelled') {
        return null
    }
    if (run.status === 'created') {
        return WizardRunProgressStep.Starting
    }

    const stage = run.status === 'failed' ? wizardRunFailureStage(run) : run.stage
    return progressStepForStage(stage) ?? (run.status === 'running' ? WizardRunProgressStep.ExecutingWizard : null)
}

export function wizardRunProgressStates(run: WizardRunApi): Record<WizardRunProgressStep, WizardRunProgressState> {
    const currentStep = wizardRunProgressStep(run)
    const currentIndex = currentStep ? WIZARD_RUN_PROGRESS_STEPS.indexOf(currentStep) : -1

    return Object.fromEntries(
        WIZARD_RUN_PROGRESS_STEPS.map((step, index) => {
            if (run.status === 'completed') {
                return [step, 'complete']
            }
            if (run.status === 'cancelled' || currentStep === null) {
                return [step, index === 0 ? 'complete' : 'pending']
            }
            if (run.status === 'failed' && index === currentIndex) {
                return [step, 'failed']
            }
            if (index < currentIndex) {
                return [step, 'complete']
            }
            return [step, index === currentIndex ? 'active' : 'pending']
        })
    ) as Record<WizardRunProgressStep, WizardRunProgressState>
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

export function selectWizardInstallRun(
    runs: WizardRunApi[],
    onboardingStartedAt: string,
    savedRun: Pick<WizardRunApi, 'id' | 'created_at'> | null = null
): WizardRunApi | null {
    const eligibleRuns = runs.filter(
        (run) =>
            run.program.id === 'posthog-integration' && Date.parse(run.created_at) >= Date.parse(onboardingStartedAt)
    )
    const newestRun = eligibleRuns.reduce<WizardRunApi | null>(
        (newest, run) => (!newest || Date.parse(run.created_at) > Date.parse(newest.created_at) ? run : newest),
        null
    )

    // Compare creation times so an older run's status update cannot replace the saved installation.
    if (savedRun && (!newestRun || Date.parse(newestRun.created_at) <= Date.parse(savedRun.created_at))) {
        return eligibleRuns.find((run) => run.id === savedRun.id) ?? null
    }
    return newestRun
}

export function wizardRunActivityLabel(run: WizardRunApi, tasks: readonly WizardRunTaskApi[]): string {
    if (run.status === 'running' && wizardRunProgressStep(run) === WizardRunProgressStep.ExecutingWizard) {
        return tasks.find((task) => task.status === 'running')?.name ?? wizardRunCurrentState(run)
    }
    return wizardRunCurrentState(run)
}

export function wizardRunElapsedSeconds(run: WizardRunApi, now: number): number {
    const end = run.finished_at ? new Date(run.finished_at).getTime() : now
    return elapsedSecondsFrom(run.started_at ?? run.created_at, end)
}

export function formatWizardRunElapsed(seconds: number): string {
    const minutes = Math.floor(seconds / 60)
    const remainder = seconds % 60
    if (minutes >= 60) {
        return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
    }
    return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
}
