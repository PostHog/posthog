import { buildGithubSetupNext } from './githubSetupNext'

describe('buildGithubSetupNext', () => {
    it('strips the project prefix so GithubIntegration adds it exactly once', () => {
        const next = buildGithubSetupNext('/project/997/inbox', { tab: 'reports' })

        // No doubled /project/<id> segment, which would return the OAuth round trip to a dead route.
        expect(next).toBe('/inbox?tab=reports&setup=github')
    })

    it('keeps a path that has no project prefix', () => {
        expect(buildGithubSetupNext('/inbox', {})).toBe('/inbox?setup=github')
    })
})
