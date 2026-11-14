import { ApiError } from 'lib/api-error'

import type { IntegrationType } from '~/types'

import type { WizardProgramApi, WizardRunCreateRequestApi } from '../generated/api.schemas'

export function wizardCloudProgram(registry: WizardProgramApi[] | null, programId: string): WizardProgramApi | null {
    return (
        registry?.find((program) => program.id === programId && program.supported_environments.includes('cloud')) ??
        null
    )
}

export function wizardCloudSetupLoading(
    integrationsLoading: boolean,
    registryLoading: boolean,
    registry: WizardProgramApi[] | null,
    registryError: boolean
): boolean {
    return integrationsLoading || registryLoading || (registry === null && !registryError)
}

export function wizardCloudSetupError(
    integrations: IntegrationType[] | null,
    registryError: boolean,
    messages: { integrations: string; registry: string }
): string | null {
    return !integrations ? messages.integrations : registryError ? messages.registry : null
}

// The API explains limits and invalid input in `detail`. Network failures have none.
export function wizardCreateRunError(errorObject: unknown, fallback: string): string {
    return errorObject instanceof ApiError && errorObject.detail ? errorObject.detail : fallback
}

export function wizardCloudRunRequest(
    program: WizardProgramApi,
    repository: string,
    idempotencyKey: string
): WizardRunCreateRequestApi {
    return {
        program_id: program.id,
        wizard_version: program.wizard_version,
        environment: 'cloud',
        workspace: { type: 'git_repository', repository },
        idempotency_key: idempotencyKey,
    }
}
