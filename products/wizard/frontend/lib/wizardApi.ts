import api from 'lib/api'

import {
    getWizardRunsArtifactsContentRetrieveUrl,
    getWizardRunsListUrl,
    wizardRunsArtifactsList,
} from '../generated/api'
import type { WizardRunArtifactApi } from '../generated/api.schemas'

// Onboarding waits for the server clock before it can select a run, so a stalled request must fall back.
export const SERVER_CLOCK_TIMEOUT_MS = 5000

export async function loadWizardOnboardingStartTime(projectId: string): Promise<string> {
    const startedAt = Date.now()
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), SERVER_CLOCK_TIMEOUT_MS)
    try {
        // nosemgrep: prefer-codegen-api -- The generated client returns only JSON, and onboarding also needs the server clock from the Date header.
        const response = await api.getResponse(getWizardRunsListUrl(projectId, { limit: 1 }), {
            signal: controller.signal,
        })
        const serverTime = Date.parse(response.headers.get('Date') ?? '')
        if (Number.isFinite(serverTime)) {
            return new Date(serverTime - (Date.now() - startedAt)).toISOString()
        }
    } catch {
        // Keep manual installation available when discovery is offline.
    } finally {
        clearTimeout(timeout)
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
