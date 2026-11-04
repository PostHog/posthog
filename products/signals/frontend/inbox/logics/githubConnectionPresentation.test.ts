import type { SignalTeamConfigApi } from '../../generated/api.schemas'
import { githubAccessBlocker, githubConnectionPresentation } from './githubConnectionPresentation'

describe('githubConnectionPresentation', () => {
    it.each(['not_connected', 'reconnect_required', 'no_repositories', 'temporarily_unavailable'] as const)(
        'uses the server research decision for %s',
        (readiness) => {
            const config: Partial<SignalTeamConfigApi> = {
                github_readiness: readiness,
                research_access: { mode: 'data_only', blocker: null },
            }
            expect(githubConnectionPresentation(config)).toMatchObject({
                blocked: false,
                title: 'Research continues without code',
                retry: readiness === 'temporarily_unavailable',
            })
            expect(
                githubConnectionPresentation({ ...config, research_access: { mode: 'blocked', blocker: readiness } })
            ).toMatchObject({ blocked: true, title: 'Self-driving is paused' })
        }
    )

    it('waits for a server decision before showing setup advice', () => {
        expect(githubConnectionPresentation(null)).toBeNull()
        expect(githubConnectionPresentation({ github_readiness: 'not_connected' })).toBeNull()
    })

    it.each([
        ['not_connected', 'blocked', 'not_connected'],
        ['reconnect_required', 'blocked', 'reconnect_required'],
        ['no_repositories', 'blocked', 'no_repositories'],
        ['temporarily_unavailable', 'blocked', null],
        ['not_connected', 'data_only', null],
        ['ready', 'code', null],
    ] as const)('feed blocker for %s with %s research is %s', (readiness, mode, expected) => {
        expect(githubAccessBlocker({ github_readiness: readiness, research_access: { mode, blocker: null } })).toBe(
            expected
        )
    })

    it('has no feed blocker before the config loads', () => {
        expect(githubAccessBlocker(null)).toBeNull()
    })
})
