import { getRepositoryConfigForTask } from './repository'

describe('getRepositoryConfigForTask', () => {
    // Reopening a GitLab task must keep its GitLab integration, or the next create sends the project path as a GitHub repo.
    it.each([
        [
            'a GitHub task',
            { repository: 'acme/widgets', github_integration: 7, repository_integration: null },
            { integrationId: 7, repository: 'acme/widgets' },
        ],
        [
            'a GitLab task',
            { repository: 'acme/platform/api', github_integration: null, repository_integration: 12 },
            { repositoryIntegrationId: 12, repository: 'acme/platform/api' },
        ],
    ])('restores the repository of %s', (_case, task, expected) => {
        expect(getRepositoryConfigForTask(task)).toEqual(expected)
    })
})
