import {
    ArtifactFile,
    collectRunArtifacts,
    groupArtifactVersions,
    taskArtifactPath,
} from 'products/posthog_ai/frontend/api/taskArtifacts'

import { TaskRunArtifactResponseApi } from '../generated/api.schemas'

export interface TaskFile {
    file: ArtifactFile
    /** Opens the session's Artifacts tab with this file selected. */
    url: string
}

export const VISIBLE_FILE_COUNT = 2

interface RunWithArtifacts {
    id: string
    artifacts?: readonly TaskRunArtifactResponseApi[] | null
}

/**
 * The files the agent handed back on the run, newest first, one per name. It uses the Artifacts tab's own
 * rules, so a chip always opens a file the tab lists. Cited PostHog objects stay out, like PostHog Desktop.
 */
export function taskFiles(taskId: string, run: RunWithArtifacts | null | undefined): TaskFile[] {
    return groupArtifactVersions(collectRunArtifacts([run]))
        .filter((file) => file.latest.type !== 'reference')
        .map((file) => ({ file, url: taskArtifactPath(taskId, file.key) }))
}
