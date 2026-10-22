import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { featureFlagRequestBlocklistLogic } from './featureFlagRequestBlocklistLogic'

describe('featureFlagRequestBlocklistLogic', () => {
    let logic: ReturnType<typeof featureFlagRequestBlocklistLogic.build>

    beforeEach(() => {
        useMocks({
            patch: {
                '/api/environments/:id': async ({ request }) => {
                    const payload = (await request.json()) as Partial<TeamType>
                    const config = payload.feature_flag_policy_config
                    return [
                        200,
                        {
                            ...MOCK_DEFAULT_TEAM,
                            ...payload,
                            feature_flag_policy_config: config && {
                                ...config,
                                blocked_hosts: config.blocked_hosts?.map((host: string) => host.toLowerCase()),
                            },
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = featureFlagRequestBlocklistLogic()
        logic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            feature_flag_policy_config: { require_tags: false, blocked_hosts: ['saved.example.com'], blocked_ips: [] },
        })
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps unsaved edits when another team setting saves', async () => {
        logic.actions.setBlockedHosts(['saved.example.com', 'draft.example.com'])

        await expectLogic(logic, () => {
            teamLogic.actions.updateCurrentTeam({ feature_flag_policy_config: { require_tags: true } })
        })
            .toDispatchActions(['updateCurrentTeamSuccess'])
            .toFinishAllListeners()

        expect(logic.values.blockedHosts).toEqual(['saved.example.com', 'draft.example.com'])
    })

    it.each([
        ['no edits', () => {}, false],
        ['an edit back to the saved list', () => logic.actions.setBlockedHosts(['saved.example.com']), false],
        ['an added IP address', () => logic.actions.setBlockedIps(['203.0.113.7']), true],
    ])('reports unsaved changes after %s', (_, edit, expected) => {
        edit()

        expect(logic.values.hasUnsavedChanges).toBe(expected)
    })

    it('shows the saved lists after a blocklist save', async () => {
        logic.actions.setBlockedHosts(['EXAMPLE.com'])

        await expectLogic(logic, () => {
            logic.actions.saveBlocklist()
        })
            .toDispatchActions(['updateCurrentTeamSuccess', 'clearDrafts'])
            .toMatchValues({ draftBlockedHosts: null, blockedHosts: ['example.com'] })
    })
})
