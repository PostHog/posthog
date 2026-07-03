import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

// Stub the Quill-based pickers: this test is about which branch control RepositorySelector renders for a
// given repo-list load state, not the pickers' internals. Stubbing also keeps githubBranchSearchLogic and
// the branches request out of the test.
jest.mock('lib/integrations/GitHubRepositoryCombobox', () => ({
    GitHubRepositoryCombobox: () => <div data-attr="repo-combobox" />,
}))
jest.mock('lib/integrations/GitHubBranchCombobox', () => ({
    GitHubBranchCombobox: () => <div data-attr="branch-combobox" />,
}))

describe('RepositorySelector', () => {
    // Imported lazily (after initKeaTests sets the current team) because the module builds a team-scoped
    // authorize URL at import time.
    let RepositorySelector: (typeof import('./RepositorySelector'))['RepositorySelector']
    let releaseRepos: () => void

    beforeEach(async () => {
        const reposLoaded = new Promise<void>((resolve) => {
            releaseRepos = resolve
        })
        useMocks({
            get: {
                '/api/environments/:team/integrations/': {
                    results: [{ id: 7, kind: 'github', display_name: 'acme', config: {} }],
                },
                // Gate the repo list so the loading → loaded transition is deterministic.
                '/api/environments/:team/integrations/7/github_repos/': async () => {
                    await reposLoaded
                    return [
                        200,
                        { repositories: [{ id: 1, name: 'widgets', full_name: 'acme/widgets' }], has_more: false },
                    ]
                },
            },
        })
        initKeaTests()
        ;({ RepositorySelector } = await import('./RepositorySelector'))
    })

    afterEach(() => {
        // Let the gated request settle so it can't leak into the next test.
        releaseRepos()
        cleanup()
    })

    // On load a persisted repo is restored before its integration's repo list has fetched. The branch picker
    // must stay the disabled "Branch" button while the repos load, and only become interactive once they have.
    // Guards against reverting the `!repositoriesLoading` gate (which left the branch picker active mid-load).
    it('keeps the branch picker disabled until the repository list has loaded', async () => {
        render(<RepositorySelector value={{ integrationId: 7, repository: 'acme/widgets' }} onChange={jest.fn()} />)

        // Repo list still loading: the disabled fallback shows, not the interactive branch combobox.
        // (Quill's Button marks itself non-interactive with aria-disabled, not the native disabled attribute.)
        expect(await screen.findByRole('button', { name: 'Branch' })).toHaveAttribute('aria-disabled', 'true')
        expect(screen.queryByTestId('branch-combobox')).not.toBeInTheDocument()

        // Repo list loaded: the interactive branch combobox replaces the fallback.
        releaseRepos()
        expect(await screen.findByTestId('branch-combobox')).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Branch' })).not.toBeInTheDocument()
    })
})
