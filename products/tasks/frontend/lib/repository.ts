import type { RepositoryConfig } from '../components/RepositorySelector'
import type { Task } from '../types'

export const getRepositoryConfigForTask = (task: Pick<Task, 'repository' | 'github_integration'>): RepositoryConfig => {
    return {
        integrationId: task.github_integration ?? undefined,
        repository: task.repository ?? undefined,
    }
}
