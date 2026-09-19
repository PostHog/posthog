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
    const response = await api.getResponse(getWizardRunsArtifactsContentRetrieveUrl(projectId, runId, artifactId))

    return response.text()
}
