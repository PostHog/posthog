import type { RepositoryConfig } from '../components/RepositorySelector'
import type { Task } from '../types'

export const getRepositoryConfigForTask = (task: Pick<Task, 'repository' | 'github_integration'>): RepositoryConfig => {
    const [organization, repository] = task.repository.split('/')
    return {
        integrationId: task.github_integration ?? (undefined as number | undefined),
        organization,
        repository,
    }
}
