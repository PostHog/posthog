import api from 'lib/api'

import { getWizardRunsArtifactsContentRetrieveUrl, wizardRunsArtifactsList } from './generated/api'
import type { WizardRunArtifactApi } from './generated/api.schemas'

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
