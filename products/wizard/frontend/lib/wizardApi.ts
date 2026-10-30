import api from 'lib/api'

import {
    getWizardRunsArtifactsContentRetrieveUrl,
    getWizardRunsListUrl,
    wizardRunsArtifactsList,
} from '../generated/api'
import type { WizardRunArtifactApi } from '../generated/api.schemas'

export async function loadWizardOnboardingStartTime(projectId: string): Promise<string> {
    const startedAt = Date.now()
    try {
        // The generated client returns only JSON; onboarding also needs the server clock.
        const response = await api.getResponse(getWizardRunsListUrl(projectId, { limit: 1 }))
        const serverTime = Date.parse(response.headers.get('Date') ?? '')
        if (Number.isFinite(serverTime)) {
            return new Date(serverTime - (Date.now() - startedAt)).toISOString()
        }
    } catch {
        // Keep manual installation available when discovery is offline.
    }
    return new Date(startedAt).toISOString()
}

export async function loadWizardRunArtifacts(projectId: string, runId: string): Promise<WizardRunArtifactApi[]> {
    return (await wizardRunsArtifactsList(projectId, runId)).results
}

export async function loadWizardRunArtifactContent(
    projectId: string,
    runId: string,
    artifactId: string
): Promise<string> {
    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a URL built at runtime and an unchecked response type. Use a generated function if one covers this endpoint.
    const response = await api.getResponse(getWizardRunsArtifactsContentRetrieveUrl(projectId, runId, artifactId))

    return response.text()
}
