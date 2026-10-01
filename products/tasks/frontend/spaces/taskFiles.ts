import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { TaskRunArtifactResponseApi } from '../generated/api.schemas'

export interface TaskFile {
    name: string
    url: string
}

export const VISIBLE_FILE_COUNT = 2

function isAgentFile(artifact: TaskRunArtifactResponseApi): boolean {
    return (
        !!artifact.id &&
        !!artifact.storage_path &&
        (artifact.type === 'output' || artifact.type === 'artifact') &&
        artifact.source === 'agent_output' &&
        !artifact.dismissed_at
    )
}

export function taskFiles(
    taskId: string,
    artifacts: readonly TaskRunArtifactResponseApi[] | null | undefined
): TaskFile[] {
    const newestByName = new Map<string, string>()
    for (const artifact of artifacts ?? []) {
        if (!isAgentFile(artifact)) {
            continue
        }
        const seen = newestByName.get(artifact.name)
        if (seen === undefined || artifact.uploaded_at > seen) {
            newestByName.set(artifact.name, artifact.uploaded_at)
        }
    }
    return [...newestByName]
        .sort(([, a], [, b]) => b.localeCompare(a))
        .map(([name]) => ({ name, url: combineUrl(urls.aiTask(taskId), { artifact: name }).url }))
}
