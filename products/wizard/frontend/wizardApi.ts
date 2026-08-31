import api from 'lib/api'

import { getWizardRunsArtifactsContentRetrieveUrl, wizardRunsArtifactsList } from './generated/api'
import type { WizardRunArtifactApi } from './generated/api.schemas'

type WizardRunArtifactPage = {
    results: WizardRunArtifactApi[]
}

export async function loadWizardRunArtifacts(projectId: string, runId: string): Promise<WizardRunArtifactApi[]> {
    const response = (await wizardRunsArtifactsList(projectId, runId)) as unknown

    if (Array.isArray(response)) {
        return response as WizardRunArtifactApi[]
    }

    return (response as WizardRunArtifactPage).results
}

export async function loadWizardRunArtifactContent(
    projectId: string,
    runId: string,
    artifactId: string
): Promise<string> {
    const response = await api.getResponse(getWizardRunsArtifactsContentRetrieveUrl(projectId, runId, artifactId))

    return response.text()
}
