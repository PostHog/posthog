import type { RunEnvironmentEnumApi, WizardRunApi } from './generated/api.schemas'

export function wizardEventProperties(
    projectId: number | string | null,
    environment: RunEnvironmentEnumApi
): Record<string, string | null> {
    return {
        event_source: 'wizard_ui',
        project_id: projectId === null ? null : String(projectId),
        environment,
        run_surface: environment,
    }
}

export function wizardRunEventProperties(run: WizardRunApi): Record<string, string | null> {
    return {
        ...wizardEventProperties(run.team_id, run.environment),
        wizard_run_id: run.id,
        ...(run.environment === 'cloud' ? { task_run_id: run.id } : {}),
        program_id: run.program.id,
        wizard_version: run.program.wizard_version,
        version: run.program.wizard_version,
        command: run.program.command[0] ?? 'default',
        workspace_type: run.workspace.type,
        status: run.status,
    }
}
