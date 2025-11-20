import { GitMetadataParser } from './gitMetadataParser'

describe('GitMetadataParser', () => {
    describe('resolveRemoteUrlWithCommitToLink', () => {
        it('should create commit link from SSH URL', () => {
            const remoteUrl = 'git@github.com:user/repo.git'
            const commitSha = 'commit-sha'
            const result = GitMetadataParser.resolveRemoteUrlWithCommitToLink(remoteUrl, commitSha)

            expect(result).toBe('https://github.com/user/repo/commit/commit-sha')
        })

        it('should create commit link from HTTPS URL', () => {
            const remoteUrl = 'https://github.com/user/repo.git'
            const commitSha = 'commit-sha'
            const result = GitMetadataParser.resolveRemoteUrlWithCommitToLink(remoteUrl, commitSha)

            expect(result).toBe('https://github.com/user/repo/commit/commit-sha')
        })

        it('should return undefined for unknown git providers', () => {
            const unknownUrl = 'https://bitbucket.org/user/repo.git'
            const commitSha = 'commit-sha'
            const result = GitMetadataParser.resolveRemoteUrlWithCommitToLink(unknownUrl, commitSha)

            expect(result).toBeUndefined()
        })
    })
})
