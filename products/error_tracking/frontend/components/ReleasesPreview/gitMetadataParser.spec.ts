import { GitMetadataParser } from './gitMetadataParser'

describe('GitMetadataParser', () => {
    describe('getCommitLink', () => {
        it.each([
            {
                description: 'should create commit link from SSH URL',
                remote_url: 'git@github.com:user/repo.git',
                expected: 'https://github.com/user/repo/commit/commit-sha',
            },
            {
                description: 'should create commit link from HTTPS URL',
                remote_url: 'https://github.com/user/repo.git',
                expected: 'https://github.com/user/repo/commit/commit-sha',
            },
            {
                description: 'should create commit link for gitlab URL',
                remote_url: 'git@gitlab.com:posthog-bot-group/posthog-bot-project.git',
                expected: 'https://gitlab.com/posthog-bot-group/posthog-bot-project/-/commit/commit-sha',
            },
            {
                description: 'should create commit link for gitlab URL',
                remote_url: 'invalid_url',
                expected: undefined,
            },
            {
                description: 'should create commit link for gitlab URL',
                remote_url: 'git@otherprovider.com:user/repo.git',
                expected: undefined,
            },
        ])('$description', ({ remote_url, expected }) => {
            const result = GitMetadataParser.getCommitLink(remote_url, 'commit-sha')
            expect(result).toBe(expected)
        })
    })

    describe('getBranchLink', () => {
        it.each([
            {
                description: 'should create commit link from SSH URL',
                remote_url: 'git@github.com:user/repo.git',
                expected: 'https://github.com/user/repo/tree/branch-name',
            },
            {
                description: 'should create commit link from HTTPS URL',
                remote_url: 'https://github.com/user/repo.git',
                expected: 'https://github.com/user/repo/tree/branch-name',
            },
            {
                description: 'should create commit link for gitlab URL',
                remote_url: 'git@gitlab.com:posthog-bot-group/posthog-bot-project.git',
                expected: 'https://gitlab.com/posthog-bot-group/posthog-bot-project/-/tree/branch-name',
            },
        ])('$description', ({ remote_url, expected }) => {
            const result = GitMetadataParser.getBranchLink(remote_url, 'branch-name')
            expect(result).toBe(expected)
        })
    })
})
