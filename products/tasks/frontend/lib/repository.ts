import type { RepositoryConfig } from '../components/RepositorySelector'
import type { Task } from '../types'

export const getRepositoryConfigForTask = (task: Pick<Task, 'repository' | 'github_integration'>): RepositoryConfig => {
    const result = (task.repository ?? '').split('/')

    if (result.length !== 2) {
        return {
            integrationId: task.github_integration ?? (undefined as number | undefined),
            organization: undefined,
            repository: undefined,
        }
    }

    const [organization, repository] = result

    return {
        integrationId: task.github_integration ?? (undefined as number | undefined),
        organization,
        repository,
    }
}
