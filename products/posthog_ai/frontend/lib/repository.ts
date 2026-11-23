import type { RepositoryConfig, Task } from '../types/taskTypes'

export const getRepositoryConfigForTask = (
    task: Pick<Task, 'repository' | 'github_integration' | 'repository_integration'>
): RepositoryConfig => {
    if (task.repository_integration) {
        return { repositoryIntegrationId: task.repository_integration, repository: task.repository ?? undefined }
    }
    return {
        integrationId: task.github_integration ?? undefined,
        repository: task.repository ?? undefined,
    }
}
