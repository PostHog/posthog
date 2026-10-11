import { operations, type OperationInfo } from './discovery'
import type { FeatureFlagsArchiveOutput } from './feature-flags/archive'
import type { FeatureFlagsListInput, FeatureFlagsListOutput } from './feature-flags/list'
import { client, createPostHogClient, type PostHogProjectClient } from './index'

export async function findFlagsWithDefaults(search: string): Promise<FeatureFlagsListOutput> {
    return client.featureFlags.list({ search, limit: 20 })
}

export function findTools(query: string): OperationInfo[] {
    return operations.filter((operation) => operation.purpose.toLowerCase().includes(query.toLowerCase())).slice(0, 5)
}

export async function findFlags(token: string, baseUrl: string, search: string): Promise<FeatureFlagsListOutput> {
    const client = createPostHogClient({ token, baseUrl })
    const input: FeatureFlagsListInput = { search, limit: 20 }

    return client.featureFlags.list(input)
}

export async function findFlagsInProject(
    token: string,
    baseUrl: string,
    projectId: number,
    search: string
): Promise<FeatureFlagsListOutput> {
    const client = createPostHogClient({ token, baseUrl, projectId })
    return client.featureFlags.list({ search, limit: 20 })
}

export async function archiveFlag(project: PostHogProjectClient, id: number): Promise<FeatureFlagsArchiveOutput> {
    return project.featureFlags.archive({ id })
}
