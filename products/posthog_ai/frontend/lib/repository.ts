import type { RepositoryConfig, Task } from '../types/taskTypes'

export const getRepositoryConfigForTask = (task: Pick<Task, 'repository' | 'github_integration'>): RepositoryConfig => {
    return {
        integrationId: task.github_integration ?? undefined,
        repository: task.repository ?? undefined,
    }
}
